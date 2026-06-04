"""Pure-core tests for the git poller's segment formatting (PHASE-01).

The hard contract is byte parity with the shell hook
``.emacs.d/satan/bin/satan-git-post-commit``. The GOLDEN line below was captured
by running that real hook against a temp repo, so these tests pin the exact
bytes the SATAN evidence consumer parses.
"""

from __future__ import annotations

from panopticon.git_poller.segment import (
    esc,
    parse_candidates,
    segment_line,
    shas_in_segment,
    slug_for,
)

# Captured from the real hook (repo path substituted to a stable value).
GOLDEN = (
    '{"repo":"/tmp/x","slug":"bar-repo",'
    '"remote":"https://github.com/foo/bar-repo.git/","sha":"886a3c3",'
    '"subject":"subject with tab and \\"quote\\" and \\\\back",'
    '"author":"Test \\"Quote\\\\Back Tab","files_changed":2,'
    '"start_ts":"2026-06-05T12:34:56+10:00",'
    '"end_ts":"2026-06-05T12:34:56+10:00"}'
)


# ---- esc ----


def test_esc_escapes_backslash() -> None:
    assert esc("a\\b") == "a\\\\b"


def test_esc_escapes_double_quote() -> None:
    assert esc('a"b') == 'a\\"b'


def test_esc_flattens_tab_to_space() -> None:
    assert esc("a\tb") == "a b"


def test_esc_combined_order() -> None:
    # backslash must be escaped before quote, else \" double-escapes.
    assert esc('x"y\\z\tw') == 'x\\"y\\\\z w'


def test_esc_noop_on_plain() -> None:
    assert esc("plain text 123") == "plain text 123"


# ---- slug_for ----


def test_slug_strips_trailing_slash_and_dotgit() -> None:
    assert slug_for("https://github.com/foo/bar-repo.git/", "/x") == "bar-repo"


def test_slug_strips_dotgit_no_trailing_slash() -> None:
    assert slug_for("https://github.com/foo/bar-repo.git", "/x") == "bar-repo"


def test_slug_scp_style_remote() -> None:
    assert slug_for("git@github.com:foo/baz.git", "/x") == "baz"


def test_slug_no_dotgit() -> None:
    assert slug_for("https://h/group/proj", "/x") == "proj"


def test_slug_empty_remote_falls_back_to_basename() -> None:
    assert slug_for("", "/home/david/dev/forgettable") == "forgettable"


def test_slug_basename_ignores_trailing_slash() -> None:
    assert slug_for("", "/home/david/dev/forgettable/") == "forgettable"


# ---- segment_line: the golden byte-match ----


def test_segment_line_byte_matches_golden_hook_output() -> None:
    line = segment_line(
        repo="/tmp/x",
        slug="bar-repo",
        remote="https://github.com/foo/bar-repo.git/",
        sha="886a3c3",
        subject='subject with\ttab and "quote" and \\back',
        author='Test "Quote\\Back\tTab',
        files_changed=2,
        ts="2026-06-05T12:34:56+10:00",
    )
    assert line == GOLDEN


def test_segment_line_files_changed_is_bare_int() -> None:
    line = segment_line(
        repo="/r",
        slug="r",
        remote="",
        sha="abc1234",
        subject="s",
        author="a",
        files_changed=0,
        ts="2026-06-05T00:00:00+00:00",
    )
    assert '"files_changed":0,' in line
    assert '"remote":"",' in line


# ---- parse_candidates ----


def test_parse_candidates_three_tokens_per_line() -> None:
    raw = (
        "deadbeefcafe deadbee 2026-06-05T12:34:56+10:00\n"
        "0123456789ab 0123456 2026-06-04T09:00:00+10:00\n"
    )
    cands = parse_candidates(raw)
    assert [c.short for c in cands] == ["deadbee", "0123456"]
    assert cands[0].full == "deadbeefcafe"
    assert cands[0].day == "2026-06-05"
    assert cands[1].day == "2026-06-04"


def test_parse_candidates_skips_blank_lines() -> None:
    raw = "\n\nabc123def456 abc123d 2026-06-05T12:00:00+10:00\n\n"
    cands = parse_candidates(raw)
    assert len(cands) == 1
    assert cands[0].short == "abc123d"


def test_parse_candidates_empty() -> None:
    assert parse_candidates("") == []


# ---- shas_in_segment: (repo, sha) keyed dedup ----


def test_shas_in_segment_returns_shas_for_matching_repo() -> None:
    lines = [
        segment_line(repo="/a", slug="a", remote="", sha="111aaaa",
                     subject="s", author="x", files_changed=1, ts="t"),
        segment_line(repo="/b", slug="b", remote="", sha="222bbbb",
                     subject="s", author="x", files_changed=1, ts="t"),
    ]
    assert shas_in_segment(lines, "/a") == {"111aaaa"}
    assert shas_in_segment(lines, "/b") == {"222bbbb"}


def test_shas_in_segment_cross_repo_prefix_does_not_collide() -> None:
    # Same short sha in two different repos must stay scoped to its repo.
    lines = [
        segment_line(repo="/a", slug="a", remote="", sha="abc1234",
                     subject="s", author="x", files_changed=1, ts="t"),
        segment_line(repo="/b", slug="b", remote="", sha="abc1234",
                     subject="s", author="x", files_changed=1, ts="t"),
    ]
    assert shas_in_segment(lines, "/a") == {"abc1234"}
    # /c never wrote anything → empty, despite the shared prefix elsewhere.
    assert shas_in_segment(lines, "/c") == set()


def test_shas_in_segment_skips_malformed_lines() -> None:
    lines = [
        "not json at all",
        "",
        segment_line(repo="/a", slug="a", remote="", sha="999zzzz",
                     subject="s", author="x", files_changed=1, ts="t"),
    ]
    assert shas_in_segment(lines, "/a") == {"999zzzz"}
