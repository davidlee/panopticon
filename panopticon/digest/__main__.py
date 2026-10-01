"""Entrypoint for ``panopticon-digest`` (design §5.1, §5.2, §5.4).

Single-shot batch job, off by default twice: nothing enables the timer, and
nothing is sent without a config that says ``enabled = true``. One run:

1. Load and strictly parse the config (missing → exit 0; malformed → exit 2).
2. ``--dry-run``: print every row's verdict; no lock, no writes, no network.
3. Not enabled → exit 0 touching nothing; API key unset → exit 2.
4. Take ``digest.lock`` (held → exit 0).
5. Walk the pending rows newest first, reading each page's text lazily, until
   ``limit`` candidates; send each through the transport and record the outcome.

Fail markers are held until the run proves the provider healthy (D13, D14);
breakers abort with exit 1. Logs carry SHAs, statuses and kinds only (I5).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from panopticon.cli import configure_logging
from panopticon.digest.client import (
    PageRejected,
    ProviderUnavailable,
    TransportFailure,
    post_json,
)
from panopticon.digest.config import ConfigError, DigestConfig, ProviderConfig, parse_config
from panopticon.digest.gate import GateConfig, Pass, Reject, Verdict, gate
from panopticon.digest.prompt import (
    PROMPT_VERSION,
    Digest,
    FailureKind,
    Page,
    Request,
    build_request,
    parse_digest,
)
from panopticon.digest.select import Judged, pending
from panopticon.digest.store import StageStore
from panopticon.fsutil import exclusive_lock
from panopticon.ingest.content import content_dir, read_index, shard_path
from panopticon.settings import config_dir, load_toml
from panopticon.store import state_dir

log = logging.getLogger("panopticon.digest")

type Transport = Callable[[str, Mapping[str, str], bytes], bytes]

STAGE = "digest"
LOCK = "digest.lock"
CONTENT_BREAKER = 5  # content failures since the last success
PROVIDER_BREAKER = 3  # transport failures / provider_error since the last success


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.verbose)
    return run(
        args.root or state_dir(),
        args.config or config_dir() / "digest.toml",
        limit=args.limit,
        dry_run=args.dry_run,
        env=os.environ,
        transport=post_json,
        now=lambda: datetime.now(UTC).astimezone(),
    )


def run(
    root: Path,
    config_path: Path,
    *,
    limit: int | None,
    dry_run: bool,
    env: Mapping[str, str],
    transport: Transport,
    now: Callable[[], datetime],
) -> int:
    """One run; returns the exit code (design §5.2 table)."""
    if not config_path.exists():
        log.info("no config at %s; nothing to do", config_path)
        return 0
    try:
        cfg = parse_config(load_toml(config_path))
    except (OSError, tomllib.TOMLDecodeError, ConfigError) as e:
        log.error("config %s: %s", config_path, e)
        return 2
    store = StageStore(root / "digest", STAGE)
    if dry_run:
        _dry_run(_walk(root, store, cfg.gate), cfg.provider)
        return 0
    if not cfg.enabled:
        log.info("digest is disabled (enabled = false); nothing to do")
        return 0
    key = env.get(cfg.provider.api_key_env)
    if not key:
        log.error("API key environment variable %s is unset", cfg.provider.api_key_env)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(root / LOCK) as acquired:
        if not acquired:
            log.info("another digest run holds the lock; skipping")
            return 0
        pages = (s for s in _walk(root, store, cfg.gate) if s.page is not None)
        batch = islice(pages, limit or cfg.max_pages_per_run)
        return _digest(batch, _Ledger(store), cfg, key, transport, now)


# --- the walk -------------------------------------------------------------------


@dataclass(frozen=True)
class _Seen:
    """A row's final verdict; ``page`` is what may be sent, set only on a full pass."""

    row: Mapping[str, Any]
    verdict: Verdict
    page: Page | None = None


def _walk(root: Path, store: StageStore, gate_cfg: GateConfig) -> Iterator[_Seen]:
    """Every row newest first; a cheap-gate pass is read and re-gated with its length."""
    content = content_dir(root)
    judged: list[Judged] = pending(read_index(content), store.done(), gate_cfg)
    for j in judged:
        if not isinstance(j.verdict, Pass):
            yield _Seen(j.row, j.verdict)
            continue
        sha = j.row["content_hash"]
        text = _read_text(shard_path(content, sha, ".json"))
        if text is None:
            log.warning("%s: content record missing or unreadable; skipped", sha)
            continue
        verdict = gate(j.row["url"], j.row["quality_score"], len(text), gate_cfg)
        page = Page(verdict.host, j.row.get("title"), text) if isinstance(verdict, Pass) else None
        yield _Seen(j.row, verdict, page)


def _read_text(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    text = raw.get("text_content") if isinstance(raw, dict) else None
    return text if isinstance(text, str) else None


# --- dry run --------------------------------------------------------------------


def _dry_run(walk: Iterable[_Seen], provider: ProviderConfig) -> None:
    """Print ``verdict<TAB>sha[<TAB>input_chars<TAB>host<TAB>title]`` per row, then counts."""
    counts: Counter[str] = Counter()
    for seen in walk:
        sha = seen.row.get("content_hash")
        if seen.page is not None:
            chars = build_request(seen.page, provider).input_chars
            title = " ".join((seen.page.title or "").split())
            print(f"pass\t{sha}\t{chars}\t{seen.page.host}\t{title}")
            counts["pass"] += 1
        elif isinstance(seen.verdict, Reject):
            print(f"{seen.verdict.reason}\t{sha}")
            counts[seen.verdict.reason] += 1
    print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))


# --- the digest loop ------------------------------------------------------------


@dataclass
class _Ledger:
    """D13/D14 outcome accounting: hold markers until a success proves the provider healthy."""

    store: StageStore
    held: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    content_streak: int = 0
    provider_streak: int = 0
    digested: int = 0
    marked: int = 0
    provider_failures: int = 0

    def success(self, sha: str, record: dict[str, Any]) -> None:
        self.store.put(sha, record)
        log.info("%s: digested", sha)
        self.digested += 1
        self.content_streak = self.provider_streak = 0
        self._flush()

    def content_failure(self, sha: str, marker: dict[str, Any]) -> bool:
        """Hold a marker; True when the content breaker trips."""
        log.warning("%s: content failure %s (status %s)", sha, marker["kind"], marker.get("status"))
        self.held.append((sha, marker))
        self.content_streak += 1
        return self.content_streak >= CONTENT_BREAKER

    def provider_failure(self, sha: str, kind: str) -> bool:
        """No marker; the page is retried next run. True when the breaker trips."""
        log.warning("%s: provider failure %s", sha, kind)
        self.provider_failures += 1
        self.provider_streak += 1
        return self.provider_streak >= PROVIDER_BREAKER

    def finish(self) -> None:
        if self.digested:
            self._flush()
        log.info(
            "done: digested=%d failure_markers=%d provider_failures=%d unmarked=%d",
            self.digested,
            self.marked,
            self.provider_failures,
            len(self.held),
        )

    def _flush(self) -> None:
        for sha, marker in self.held:
            self.store.put_failure(sha, marker)
        self.marked += len(self.held)
        self.held.clear()


def _digest(
    batch: Iterable[_Seen],
    ledger: _Ledger,
    cfg: DigestConfig,
    key: str,
    transport: Transport,
    now: Callable[[], datetime],
) -> int:
    headers = {"Authorization": f"Bearer {key}"}
    for seen in batch:
        assert seen.page is not None
        sha = seen.row["content_hash"]
        request = build_request(seen.page, cfg.provider)
        at = now().isoformat()
        try:
            reply = transport(cfg.provider.endpoint, headers, json.dumps(request.body).encode())
        except ProviderUnavailable as e:
            log.error("%s: provider unavailable (status %s); aborting", sha, e.status)
            return 1
        except PageRejected as e:
            tripped = ledger.content_failure(sha, _marker("page_rejected", e.status, at, cfg))
        except TransportFailure as e:
            tripped = ledger.provider_failure(sha, f"transport ({e})")
        else:
            match parse_digest(reply):
                case Digest() as digest:
                    ledger.success(sha, _record(seen, request, digest, at, cfg))
                    tripped = False
                case failure if failure.kind is FailureKind.PROVIDER_ERROR:
                    tripped = ledger.provider_failure(sha, failure.kind)
                case failure:
                    tripped = ledger.content_failure(sha, _marker(failure.kind, None, at, cfg))
        if tripped:
            log.error(
                "breaker tripped (content=%d, provider=%d since the last success); "
                "aborting, %d held marker(s) discarded",
                ledger.content_streak,
                ledger.provider_streak,
                len(ledger.held),
            )
            return 1
    ledger.finish()
    return 0


def _provenance(cfg: DigestConfig) -> dict[str, str]:
    """The egress ledger: which provider and model saw the text, under which prompt."""
    return {
        "endpoint": cfg.provider.endpoint,
        "model": cfg.provider.model,
        "prompt_version": PROMPT_VERSION,
    }


def _record(
    seen: _Seen, request: Request, digest: Digest, at: str, cfg: DigestConfig
) -> dict[str, Any]:
    """Design §5.3 record fields."""
    assert seen.page is not None
    row = seen.row
    return {
        "content_hash": row["content_hash"],
        "url": row["url"],
        "host": seen.page.host,
        "title": row.get("title"),
        "captured_at": row["captured_at"],
        "digested_at": at,
        **_provenance(cfg),
        "input_chars": request.input_chars,
        "input_truncated": request.input_truncated,
        **asdict(digest),
    }


def _marker(kind: str, status: int | None, at: str, cfg: DigestConfig) -> dict[str, Any]:
    status_field = {} if status is None else {"status": status}
    return {"kind": kind, **status_field, "at": at, **_provenance(cfg)}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="panopticon-digest")
    p.add_argument(
        "--root", type=Path, default=None, help="state root (default: $XDG_STATE_HOME/behaviour)"
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="config file (default: $XDG_CONFIG_HOME/panopticon/digest.toml)",
    )
    p.add_argument(
        "--limit", type=_positive_int, default=None, help="pages this run (overrides config)"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print every row's verdict; no network, no writes (ignores enabled and the key)",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v INFO, -vv DEBUG")
    return p.parse_args(argv)


def _positive_int(s: str) -> int:
    n = int(s)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


if __name__ == "__main__":
    sys.exit(main())
