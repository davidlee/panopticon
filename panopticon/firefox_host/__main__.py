"""Entrypoint for ``panopticon-firefox-host``.

Two modes:

* default — long-running native-messaging host. Reads framed messages
  from stdin, validates and redacts them, and appends Events through
  :class:`panopticon.store.RawStore` with ``source="firefox"``. Exits 0
  on clean EOF (Firefox closing the port).
* ``install-manifest`` — render and write the per-user Firefox
  native-messaging manifest, then exit.

Stdout is reserved for the wire protocol (we don't reply, but we must
not pollute it); all logging goes to stderr.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, BinaryIO

from panopticon.firefox_host import install as install_mod
from panopticon.firefox_host import protocol, validate
from panopticon.ingest.content import content_dir
from panopticon.schema import make_event
from panopticon.store import RawStore, state_dir

log = logging.getLogger("panopticon.firefox_host")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if args.command == "install-manifest":
        return _cmd_install_manifest(args)
    return _cmd_run(args)


def _cmd_run(args: argparse.Namespace) -> int:
    root = args.root or state_dir()
    with RawStore(source="firefox", root=root) as store:
        run_loop(
            sys.stdin.buffer,
            store,
            record_file_urls=args.record_file_urls,
        )
    return 0


def run_loop(
    stdin: BinaryIO,
    store: RawStore,
    *,
    record_file_urls: bool = False,
) -> None:
    """Read framed messages from ``stdin`` until EOF and append to ``store``.

    ``browser_content_extracted`` events are routed to :class:`ContentStore`
    instead of the raw JSONL tier (their payloads are too large for the
    per-day raw files and serve a different consumer).
    """
    ct_root = content_dir(root=store.root)

    while True:
        try:
            msg = protocol.read_message(stdin)
        except protocol.ProtocolError as exc:
            log.warning("dropping malformed frame: %s", exc)
            continue
        if msg is None:
            return
        try:
            event_name, ts, fields = validate.validate_and_redact(
                msg, record_file_urls=record_file_urls
            )
        except validate.ValidationError as exc:
            log.debug("dropped event: %s", exc)
            continue

        if event_name == "browser_content_extracted":
            _handle_content_extracted(ct_root, ts, fields)
            continue

        store.write(make_event("firefox", event_name, ts=ts, **fields))


def _cmd_install_manifest(args: argparse.Namespace) -> int:
    manifest = install_mod.build_manifest(
        install_mod.resolve_host_binary(args.binary),
        extension_id=args.extension_id,
    )
    if args.print:
        sys.stdout.write(manifest.to_json() + "\n")
        return 0
    target = install_mod.install(
        binary=args.binary,
        extension_id=args.extension_id,
        manifest_path=args.manifest_path,
    )
    log.info("wrote manifest to %s", target)
    sys.stdout.write(f"{target}\n")
    return 0


def _handle_content_extracted(
    ct_root: Path,
    ts: str,
    fields: dict[str, Any],
) -> None:
    """Route a browser_content_extracted event to the ContentStore."""
    from panopticon.ingest.content import ContentStore

    domain = fields.get("domain") or "unknown"
    url = fields.get("url", "")
    error = fields.get("error")

    if error:
        log.debug("content extraction failed for %s: %s", url, error)
        return

    text_content = fields.get("textContent", "")
    content_html = fields.get("contentHtml", "")

    if not text_content or not content_html:
        log.debug("empty content for %s, skipping", url)
        return

    store = ContentStore(root=ct_root, domain=domain)
    entry = store.store(
        url=url,
        title=fields.get("title"),
        text_content=text_content,
        content_html=content_html,
        byline=fields.get("byline"),
        excerpt=fields.get("excerpt"),
        site_name=fields.get("siteName"),
        published_time=fields.get("publishedTime"),
        captured_at=fields.get("capturedAt") or ts,
        extractor="readability",
    )
    if entry:
        log.info("content stored: hash=%s url=%s quality=%s",
                 entry["content_hash"][:12], url, entry["quality_score"])
    else:
        log.debug("content duplicate: %s", url)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI args.

    Firefox launches the host with two positional arguments — the
    absolute manifest path and the calling extension ID — neither of
    which we use. To avoid argparse erroring on them we detect the
    install-manifest subcommand explicitly and otherwise treat every
    positional as opaque "Firefox launcher noise" to ignore.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "install-manifest":
        return _parse_install_args(raw[1:])
    return _parse_run_args(raw)


def _parse_run_args(raw: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="panopticon-firefox-host", add_help=False)
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--record-file-urls", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    # Tolerate Firefox's manifest-path + extension-id positionals.
    args, _ignored = p.parse_known_args(raw)
    if args.help:
        _print_run_help()
        sys.exit(0)
    args.command = "run"
    return args


def _parse_install_args(raw: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="panopticon-firefox-host install-manifest")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument(
        "--binary",
        default=None,
        help="absolute path to host binary (default: resolve from PATH)",
    )
    p.add_argument(
        "--extension-id",
        default=install_mod.EXTENSION_ID,
        help=f"extension ID to allow (default: {install_mod.EXTENSION_ID})",
    )
    p.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help="override manifest output path",
    )
    p.add_argument(
        "--print",
        action="store_true",
        help="dump manifest JSON to stdout instead of writing",
    )
    args = p.parse_args(raw)
    args.command = "install-manifest"
    return args


def _print_run_help() -> None:
    sys.stdout.write(
        "usage: panopticon-firefox-host [-v] [--root DIR] [--record-file-urls]\n"
        "       panopticon-firefox-host install-manifest [--binary PATH] "
        "[--extension-id ID] [--manifest-path PATH] [--print]\n"
        "\n"
        "Reads length-prefixed JSON from stdin and appends events to\n"
        "$XDG_STATE_HOME/behaviour/raw/firefox-YYYY-MM-DD.jsonl. Designed to be\n"
        "launched by Firefox as a native messaging host; extra positional\n"
        "arguments (manifest path, extension id) are ignored.\n"
    )


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    sys.exit(main())
