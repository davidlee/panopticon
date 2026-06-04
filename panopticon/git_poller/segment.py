"""Pure formatting core for the git-commit producer.

The git feed is a *foreign* contract: one flat JSON object per line, written
straight to ``segments/git-<day>.jsonl`` and parsed by the SATAN evidence
consumer (Emacs lisp). It is **not** a panopticon :class:`~panopticon.schema.Event`
and must be byte-compatible with the shell hook
``.emacs.d/satan/bin/satan-git-post-commit`` — same field order, same escaping,
same slug derivation. So the line is hand-built here, not routed through
:meth:`Event.to_json_line` (which would escape differently).

Everything in this module is pure: no git, no disk, no clock. The impure shell
(subprocess + filesystem) lives in :mod:`panopticon.git_poller.poller`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


def esc(s: str) -> str:
    """Replicate the hook's ``esc()``: escape ``\\`` and ``"``, flatten tab→space.

    Order matters — backslashes are doubled *before* quotes are escaped, so the
    backslash introduced by ``\\"`` is not itself re-doubled.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", " ")


def slug_for(remote: str, toplevel: str) -> str:
    """Derive the ``project:<slug>`` handle exactly as the hook does.

    With a remote: strip one trailing ``/``, take the basename, strip a ``.git``
    suffix (the hook's ``sed 's#/$##; s#.*/##; s#\\.git$##'``). Otherwise fall
    back to the working-tree basename.
    """
    if remote:
        s = remote[:-1] if remote.endswith("/") else remote
        s = s.rsplit("/", 1)[-1]
        return s[:-4] if s.endswith(".git") else s
    return toplevel.rstrip("/").rsplit("/", 1)[-1]


def segment_line(
    *,
    repo: str,
    slug: str,
    remote: str,
    sha: str,
    subject: str,
    author: str,
    files_changed: int,
    ts: str,
) -> str:
    """Assemble one segment line, byte-identical to the hook's ``printf`` template.

    ``start_ts == end_ts == ts`` (the commit instant — load-bearing for the
    consumer's windowing/sort). ``files_changed`` is a bare JSON number. String
    fields are :func:`esc`'d; ``ts`` is trusted (``%cI`` has no escapable bytes).
    """
    return (
        f'{{"repo":"{esc(repo)}","slug":"{esc(slug)}","remote":"{esc(remote)}",'
        f'"sha":"{esc(sha)}","subject":"{esc(subject)}","author":"{esc(author)}",'
        f'"files_changed":{files_changed},'
        f'"start_ts":"{ts}","end_ts":"{ts}"}}'
    )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One commit enumerated by the pass-1 ``git log`` (before any per-commit fetch)."""

    full: str
    short: str
    cI: str

    @property
    def day(self) -> str:
        """The day-file key: committer-date local date (``%cI[:10]``)."""
        return self.cI[:10]


def parse_candidates(raw: str) -> list[Candidate]:
    """Parse pass-1 output: one ``"<full_sha> <short_sha> <cI>"`` line per commit.

    All three tokens are whitespace-free (hex, hex, ISO8601-with-offset), so a
    plain split is safe. Blank lines are tolerated.
    """
    out: list[Candidate] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        full, short, cI = line.split()
        out.append(Candidate(full=full, short=short, cI=cI))
    return out


def shas_in_segment(lines: list[str], repo: str) -> set[str]:
    """Return the set of ``sha`` already recorded for ``repo`` in a day-file.

    Dedup is keyed on ``(repo, sha)``: a short-sha prefix shared across two repos
    must not false-skip. Malformed lines are skipped (mirrors
    :func:`panopticon.schema.iter_jsonl` tolerance).
    """
    seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("repo") == repo and "sha" in obj:
            seen.add(obj["sha"])
    return seen
