from __future__ import annotations

from panopticon.sway_watcher.__main__ import main


def test_wrapper_forces_compositor_sway(monkeypatch):
    """panopticon-sway is now an alias for panopticon-desktop --compositor sway,
    forwarding the caller's remaining args."""
    captured = {}

    def fake_desktop_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(
        "panopticon.sway_watcher.__main__._desktop_main", fake_desktop_main
    )
    rc = main(["--state-dir", "/tmp/behaviour", "-v"])
    assert rc == 0
    assert captured["argv"] == ["--compositor", "sway", "--state-dir", "/tmp/behaviour", "-v"]


def test_wrapper_passes_empty_args(monkeypatch):
    captured = {}

    def fake_desktop_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(
        "panopticon.sway_watcher.__main__._desktop_main", fake_desktop_main
    )
    assert main([]) == 0
    assert captured["argv"] == ["--compositor", "sway"]
