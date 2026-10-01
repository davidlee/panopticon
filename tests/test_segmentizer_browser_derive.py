from __future__ import annotations

from panopticon.schema import make_event
from panopticon.segmentizer.browser import derive_browser_segments

T = "2026-05-19T10:{m:02d}:{s:02d}.000+10:00"


def ts(m: int, s: int = 0) -> str:
    return T.format(m=m, s=s)


def snap(t: str, **f):
    return make_event("firefox", "browser_snapshot", ts=t, **f)


def active(t: str, **f):
    return make_event("firefox", "browser_tab_active", ts=t, **f)


def nav(t: str, **f):
    return make_event("firefox", "browser_navigation", ts=t, **f)


def updated(t: str, **f):
    return make_event("firefox", "browser_tab_updated", ts=t, **f)


def wfocus(t: str, focused: bool, window_id: int = 1):
    return make_event(
        "firefox", "browser_window_focus", ts=t, window_id=window_id, focused=focused
    )


def idle(t: str, state: str):
    return make_event("firefox", "browser_idle_state", ts=t, state=state)


# ---- boundary ----


def test_empty_stream_yields_nothing():
    assert list(derive_browser_segments([])) == []


def test_open_without_close_at_yields_nothing():
    assert list(derive_browser_segments([snap(ts(0), url="https://a.example/")])) == []


def test_close_at_emits_trailing_segment():
    segs = list(
        derive_browser_segments(
            [snap(ts(0), window_id=1, tab_id=42, url="https://a.example/", title="A")],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    s = segs[0]
    assert s.event == "browser_tab_segment"
    assert s.source == "firefox"
    f = s.fields
    assert f["start_ts"] == ts(0)
    assert f["end_ts"] == ts(5)
    assert f["duration_s"] == 300.0
    assert f["window_id"] == 1
    assert f["tab_id"] == 42
    assert f["url"] == "https://a.example/"
    assert f["title_start"] == "A"
    assert f["title_end"] == "A"
    assert f["audible"] is False


# ---- transitions ----


def test_tab_active_closes_and_opens():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                active(ts(2), window_id=1, tab_id=43, url="https://b.example/"),
            ],
            close_at=ts(5),
        )
    )
    assert [s.fields["tab_id"] for s in segs] == [42, 43]
    assert segs[0].fields["end_ts"] == ts(2)
    assert segs[1].fields["start_ts"] == ts(2)
    assert segs[1].fields["end_ts"] == ts(5)


def test_navigation_to_new_url_splits():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/x"),
                nav(
                    ts(2),
                    kind="committed",
                    window_id=1,
                    tab_id=42,
                    url="https://a.example/y",
                ),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 2
    assert segs[0].fields["url"] == "https://a.example/x"
    assert segs[1].fields["url"] == "https://a.example/y"


def test_navigation_to_same_url_does_not_split():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/x"),
                nav(
                    ts(2),
                    kind="committed",
                    window_id=1,
                    tab_id=42,
                    url="https://a.example/x",
                ),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1


def test_history_state_updated_splits_on_new_url():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://gh.example/repo"),
                nav(
                    ts(2),
                    kind="history_state_updated",
                    window_id=1,
                    tab_id=42,
                    url="https://gh.example/repo/pulls",
                ),
            ],
            close_at=ts(5),
        )
    )
    assert [s.fields["url"] for s in segs] == [
        "https://gh.example/repo",
        "https://gh.example/repo/pulls",
    ]


def test_tab_updated_title_only_refines():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/", title="Old"),
                updated(ts(2), window_id=1, tab_id=42, title="New"),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    assert segs[0].fields["title_start"] == "Old"
    assert segs[0].fields["title_end"] == "New"


def test_tab_updated_audible_refines():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                updated(ts(2), window_id=1, tab_id=42, audible=True),
            ],
            close_at=ts(5),
        )
    )
    assert segs[0].fields["audible"] is True


def test_tab_updated_with_new_url_splits():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                updated(ts(2), window_id=1, tab_id=42, url="https://b.example/"),
            ],
            close_at=ts(5),
        )
    )
    assert [s.fields["url"] for s in segs] == [
        "https://a.example/",
        "https://b.example/",
    ]


# ---- focus / idle ----


def test_window_focus_false_closes_segment():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                wfocus(ts(2), focused=False),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    assert segs[0].fields["end_ts"] == ts(2)


def test_window_focus_true_alone_does_not_open():
    # No prior snapshot/active; just an unsolicited focused=true.
    segs = list(
        derive_browser_segments(
            [wfocus(ts(0), focused=True)],
            close_at=ts(5),
        )
    )
    assert segs == []


def test_focus_off_then_reopen_via_tab_active():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                wfocus(ts(1), focused=False),
                active(ts(3), window_id=1, tab_id=42, url="https://a.example/"),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 2
    assert segs[0].fields["end_ts"] == ts(1)
    assert segs[1].fields["start_ts"] == ts(3)


def test_idle_closes_segment():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                idle(ts(2), state="idle"),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    assert segs[0].fields["end_ts"] == ts(2)


def test_locked_state_closes_segment():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                idle(ts(2), state="locked"),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    assert segs[0].fields["end_ts"] == ts(2)


def test_active_idle_state_does_not_close():
    segs = list(
        derive_browser_segments(
            [
                snap(ts(0), window_id=1, tab_id=42, url="https://a.example/"),
                idle(ts(2), state="active"),
            ],
            close_at=ts(5),
        )
    )
    assert len(segs) == 1
    assert segs[0].fields["end_ts"] == ts(5)


def test_segment_carries_domain():
    segs = list(
        derive_browser_segments(
            [
                snap(
                    ts(0),
                    window_id=1,
                    tab_id=42,
                    url="https://a.example/x",
                    domain="a.example",
                ),
            ],
            close_at=ts(5),
        )
    )
    assert segs[0].fields["domain"] == "a.example"
