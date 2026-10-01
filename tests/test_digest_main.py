"""SL-006 VT-3..6: the ``panopticon-digest`` run (design §5.1, §5.2 exit table, §5.4, I1–I5).

The run is driven against a real content store in ``tmp_path`` and a scripted
fake transport; nothing here touches the network.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from panopticon.digest.__main__ import main, run
from panopticon.digest.client import PageRejected, ProviderUnavailable, TransportFailure
from panopticon.digest.store import StageStore
from panopticon.fsutil import exclusive_lock
from panopticon.ingest.content import ContentStore, content_dir

KEY_ENV = "TEST_DIGEST_KEY"
KEY = "sk-SECRET-KEY-0001"
ENDPOINT = "https://provider.example/v1/chat"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


# --- fixtures -----------------------------------------------------------------


def write_config(path: Path, *, enabled: bool = True, extra: str = "") -> Path:
    path.write_text(
        f"enabled = {str(enabled).lower()}\n{extra}\n"
        f'[digest]\nmodel = "test/model"\nendpoint = "{ENDPOINT}"\napi_key_env = "{KEY_ENV}"\n',
        encoding="utf-8",
    )
    return path


def add_page(
    root: Path, n: int, *, host: str = "example.org", path: str = "", chars: int = 2000
) -> str:
    """Store page ``n`` (captured ``n`` minutes after T0) and return its SHA."""
    text = f"PAGETEXT-{n:03d} " + "A long sentence of ordinary prose about a subject. " * (
        chars // 50
    )
    entry = ContentStore(root=content_dir(root), domain=host).store(
        url=f"https://{host}/{path or f'page-{n}'}",
        title=f"Title {n}",
        text_content=text,
        content_html="<p>prose</p>",
        captured_at=(T0 + timedelta(minutes=n)).isoformat(),
    )
    assert entry is not None
    return entry["content_hash"]


def digest_reply(summary: str = "s") -> bytes:
    content = json.dumps({"summary": summary, "claims": ["c"], "entities": []})
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


NOT_JSON = json.dumps({"choices": [{"message": {"content": "nope"}}]}).encode()
PROVIDER_ERROR = json.dumps({"error": {"message": "overloaded"}}).encode()


@dataclass
class FakeTransport:
    """Answers each call with the next scripted reply or exception; then succeeds."""

    script: list[bytes | Exception] = field(default_factory=list)
    calls: list[bytes] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> bytes:
        assert url == ENDPOINT
        self.calls.append(body)
        self.headers.append(dict(headers))
        step = self.script.pop(0) if self.script else digest_reply()
        if isinstance(step, Exception):
            raise step
        return step


@dataclass
class Env:
    root: Path
    config: Path
    transport: FakeTransport

    def run(self, *, limit: int | None = None, dry_run: bool = False, key: bool = True) -> int:
        return run(
            self.root,
            self.config,
            limit=limit,
            dry_run=dry_run,
            env={KEY_ENV: KEY} if key else {},
            transport=self.transport,
            now=lambda: T0,
        )

    def records(self) -> list[dict]:
        return _load_all(self.root / "digest", "*.digest.json")

    def markers(self) -> list[dict]:
        return _load_all(self.root / "digest", "*.digest.fail.json")


def _load_all(root: Path, pattern: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob(f"??/{pattern}"))]


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    root = tmp_path / "state"
    return Env(root, write_config(tmp_path / "digest.toml"), FakeTransport())


def sent_texts(transport: FakeTransport) -> list[str]:
    """Which page each call carried, by its PAGETEXT marker."""
    out = []
    for body in transport.calls:
        user = json.loads(body)["messages"][1]["content"]
        out.append(user[user.index("PAGETEXT-") :][:12])
    return out


# --- happy path, I4 -----------------------------------------------------------


def test_run_digests_each_candidate_newest_first_and_records_it(env: Env):
    old, new = add_page(env.root, 1), add_page(env.root, 2)
    assert env.run() == 0
    assert sent_texts(env.transport) == ["PAGETEXT-002", "PAGETEXT-001"]
    by_sha = {r["content_hash"]: r for r in env.records()}
    assert set(by_sha) == {old, new}
    rec = by_sha[new]
    assert rec["url"] == "https://example.org/page-2"
    assert rec["host"] == "example.org"
    assert rec["title"] == "Title 2"
    assert rec["captured_at"] == (T0 + timedelta(minutes=2)).isoformat()
    assert rec["digested_at"] == T0.isoformat()
    assert (rec["endpoint"], rec["model"], rec["prompt_version"]) == (ENDPOINT, "test/model", "1")
    assert rec["input_truncated"] is False and rec["input_chars"] > 1500
    assert (rec["summary"], rec["claims"], rec["entities"]) == ("s", ["c"], [])


def test_run_sends_the_key_only_as_a_bearer_header(env: Env):
    add_page(env.root, 1)
    env.run()
    assert env.transport.headers == [{"Authorization": f"Bearer {KEY}"}]
    assert KEY.encode() not in env.transport.calls[0]


def test_rerun_never_resends_a_done_page(env: Env):
    """I4: records and fail markers both make a SHA done."""
    for n in range(3):
        add_page(env.root, n)
    env.transport.script = [NOT_JSON]
    assert env.run() == 0
    assert (len(env.records()), len(env.markers())) == (2, 1)
    env.transport.calls.clear()
    assert env.run() == 0
    assert env.transport.calls == []


# --- selection: limit, I1 -----------------------------------------------------


def test_limit_stops_the_walk_after_that_many_candidates(env: Env):
    for n in range(4):
        add_page(env.root, n)
    assert env.run(limit=2) == 0
    assert sent_texts(env.transport) == ["PAGETEXT-003", "PAGETEXT-002"]


def test_max_pages_per_run_is_the_default_limit(env: Env, tmp_path: Path):
    write_config(env.config, extra="max_pages_per_run = 1")
    for n in range(3):
        add_page(env.root, n)
    assert env.run() == 0
    assert len(env.transport.calls) == 1


def test_too_short_pages_do_not_count_against_the_limit(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2, chars=1000)
    assert env.run(limit=1) == 0
    assert sent_texts(env.transport) == ["PAGETEXT-001"]


def test_gated_pages_never_reach_the_transport(env: Env):
    """I1: denied, local and too-short pages are never sent."""
    add_page(env.root, 1, host="mail.google.com")
    add_page(env.root, 2, host="intranet")
    add_page(env.root, 3, chars=1000)
    assert env.run() == 0
    assert env.transport.calls == []


def test_only_host_title_and_text_leave_the_host(env: Env):
    """I1: the URL path never leaves the host."""
    add_page(env.root, 1, path="share/secret-token-xyz")
    env.run()
    [body] = env.transport.calls
    assert b"secret-token-xyz" not in body
    assert b"example.org" in body and b"Title 1" in body and b"PAGETEXT-001" in body


def test_missing_content_record_is_skipped(env: Env, caplog: pytest.LogCaptureFixture):
    sha = add_page(env.root, 2)
    add_page(env.root, 1)
    (content_dir(env.root) / sha[:2] / f"{sha}.json").unlink()
    assert env.run() == 0
    assert sent_texts(env.transport) == ["PAGETEXT-001"]
    assert sha in caplog.text


# --- I3: disabled / no config / dry-run -------------------------------------


def test_no_config_touches_nothing(env: Env):
    add_page(env.root, 1)
    env.config.unlink()
    before = snapshot(env.root)
    assert env.run() == 0
    assert snapshot(env.root) == before
    assert env.transport.calls == []


def test_disabled_touches_nothing_not_even_the_lock(env: Env):
    add_page(env.root, 1)
    write_config(env.config, enabled=False)
    before = snapshot(env.root)
    assert env.run() == 0
    assert snapshot(env.root) == before
    assert not (env.root / "digest.lock").exists()
    assert env.transport.calls == []


def test_dry_run_ignores_enabled_and_key_and_prints_verdicts(
    env: Env, capsys: pytest.CaptureFixture[str]
):
    write_config(env.config, enabled=False)
    good = add_page(env.root, 1)
    denied = add_page(env.root, 2, host="google.com")
    short = add_page(env.root, 3, chars=1000)
    done = add_page(env.root, 4)
    StageStore(env.root / "digest", "digest").put(done, {})
    before = snapshot(env.root)

    assert env.run(dry_run=True, key=False) == 0

    assert snapshot(env.root) == before
    assert not (env.root / "digest.lock").exists()
    assert env.transport.calls == []
    lines = {line.split("\t")[1]: line.split("\t") for line in capsys.readouterr().out.splitlines()
             if "\t" in line}  # fmt: skip
    assert lines[good][0] == "pass" and lines[good][3:] == ["example.org", "Title 1"]
    assert int(lines[good][2]) > 1500
    assert lines[denied][0] == "denied_domain"
    assert lines[short][0] == "too_short"
    assert lines[done][0] == "done"


def test_dry_run_reports_every_row_beyond_the_limit(env: Env, capsys: pytest.CaptureFixture[str]):
    for n in range(3):
        add_page(env.root, n)
    env.run(dry_run=True, limit=1)
    assert capsys.readouterr().out.count("pass\t") == 3


# --- D13 / D14: failure handling ----------------------------------------------


def test_content_failure_then_success_writes_the_marker(env: Env):
    add_page(env.root, 1)
    failed = add_page(env.root, 2)
    env.transport.script = [NOT_JSON]
    assert env.run() == 0
    [marker] = env.markers()
    assert marker["kind"] == "not_json"
    assert (marker["endpoint"], marker["model"], marker["prompt_version"]) == (
        ENDPOINT,
        "test/model",
        "1",
    )
    assert StageStore(env.root / "digest", "digest").done() >= {failed}


def test_content_failures_with_no_success_write_no_marker(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2)
    env.transport.script = [NOT_JSON, NOT_JSON]
    assert env.run() == 0
    assert env.markers() == [] and env.records() == []


def test_content_failure_after_the_last_success_is_flushed_at_the_end(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2)
    env.transport.script = [digest_reply(), NOT_JSON]
    assert env.run() == 0
    assert len(env.markers()) == 1


def test_five_content_failures_abort_with_no_markers(env: Env):
    for n in range(7):
        add_page(env.root, n)
    env.transport.script = [digest_reply()] + [NOT_JSON] * 5
    assert env.run() == 1
    assert len(env.transport.calls) == 6
    assert (len(env.records()), env.markers()) == (1, [])


def test_a_success_resets_the_content_failure_streak(env: Env):
    for n in range(10):
        add_page(env.root, n)
    env.transport.script = [NOT_JSON] * 4 + [digest_reply()] + [NOT_JSON] * 4
    assert env.run() == 0
    assert (len(env.records()), len(env.markers())) == (2, 8)


def test_page_rejected_is_a_content_failure_marker_with_status(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2)
    env.transport.script = [PageRejected(403)]
    assert env.run() == 0
    [marker] = env.markers()
    assert (marker["kind"], marker["status"]) == ("page_rejected", 403)


def test_provider_unavailable_aborts_at_once_and_discards_held_markers(env: Env):
    for n in range(6):
        add_page(env.root, n)
    env.transport.script = [NOT_JSON, digest_reply(), NOT_JSON, ProviderUnavailable(401)]
    assert env.run() == 1
    assert len(env.transport.calls) == 4
    assert (len(env.records()), len(env.markers())) == (1, 1)


@pytest.mark.parametrize(
    "streak",
    [
        [TransportFailure("x")] * 3,
        [TransportFailure("x"), PROVIDER_ERROR, TransportFailure("x")],
    ],
    ids=["transport", "mixed-provider-error"],
)
def test_three_transport_or_provider_failures_abort(env: Env, streak: list):
    for n in range(5):
        add_page(env.root, n)
    env.transport.script = list(streak)
    assert env.run() == 1
    assert len(env.transport.calls) == 3
    assert env.markers() == []


def test_transport_failures_never_write_markers_and_retry_next_run(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2)
    env.transport.script = [TransportFailure("x"), PROVIDER_ERROR]
    assert env.run() == 0
    assert (env.records(), env.markers()) == ([], [])
    assert env.run() == 0
    assert len(env.records()) == 2


# --- I5 -----------------------------------------------------------------------


def test_logs_hold_no_page_text_body_or_key(env: Env, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    for n in range(8):
        add_page(env.root, n)
    env.transport.script = [
        NOT_JSON,
        PageRejected(403),
        TransportFailure("x"),
        PROVIDER_ERROR,
        digest_reply("SUMMARY-TEXT"),
        ProviderUnavailable(401),
    ]
    env.run()
    assert caplog.records
    for needle in ("PAGETEXT", "prose", KEY, "SUMMARY-TEXT", '"messages"', "Bearer"):
        assert needle not in caplog.text


# --- exit-code table (design §5.2) via main() ------------------------------------


def _main(env: Env, *extra: str) -> int:
    return main(["--root", str(env.root), "--config", str(env.config), *extra])


def test_exit_0_with_no_config(env: Env):
    env.config.unlink()
    assert _main(env) == 0
    assert _main(env, "--dry-run") == 0


@pytest.mark.parametrize(
    "text",
    ["enabled = maybe\n", 'enabled = true\napi_key = "x"\n[digest]\nmodel = "m"\n'],
    ids=["toml-syntax", "unknown-key"],
)
def test_exit_2_with_malformed_config(env: Env, text: str):
    env.config.write_text(text, encoding="utf-8")
    assert _main(env) == 2
    assert _main(env, "--dry-run") == 2


def test_exit_0_when_disabled(env: Env):
    write_config(env.config, enabled=False)
    assert _main(env) == 0


def test_exit_2_when_key_missing(env: Env, monkeypatch: pytest.MonkeyPatch,
                                 caplog: pytest.LogCaptureFixture):  # fmt: skip
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert _main(env) == 2
    assert KEY_ENV in caplog.text


def test_exit_0_when_lock_held(env: Env):
    add_page(env.root, 1)
    with exclusive_lock(env.root / "digest.lock") as acquired:
        assert acquired
        assert env.run() == 0
    assert env.transport.calls == []


def test_exit_0_when_run_completes_with_content_failures(env: Env):
    add_page(env.root, 1)
    add_page(env.root, 2)
    env.transport.script = [PageRejected(400)]
    assert env.run() == 0


def test_exit_1_when_a_breaker_trips(env: Env):
    add_page(env.root, 1)
    env.transport.script = [ProviderUnavailable(402)]
    assert env.run() == 1
