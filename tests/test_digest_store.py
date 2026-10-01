"""SL-006 VT-2: StageStore — per-SHA stage records and fail markers (design §5.3, D12)."""

from __future__ import annotations

import json
from pathlib import Path

from panopticon.digest.store import StageStore

SHA_A = "a" * 64
SHA_B = "b1" + "0" * 62


def _marker() -> dict[str, object]:
    return {
        "kind": "bad_shape",
        "at": "2026-10-01T00:00:00+00:00",
        "endpoint": "https://provider.example/v1",
        "model": "m",
        "prompt_version": "1",
    }


def test_empty_store_has_nothing_done(tmp_path: Path):
    assert StageStore(tmp_path / "digest", "digest").done() == set()


def test_put_round_trips_a_record_at_its_sharded_path(tmp_path: Path):
    store = StageStore(tmp_path, "digest")
    store.put(SHA_B, {"summary": "s", "claims": ["c"]})
    path = tmp_path / "b1" / f"{SHA_B}.digest.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"summary": "s", "claims": ["c"]}
    assert store.done() == {SHA_B}


def test_fail_marker_counts_as_done_and_carries_endpoint(tmp_path: Path):
    store = StageStore(tmp_path, "digest")
    store.put_failure(SHA_A, _marker())
    path = tmp_path / "aa" / f"{SHA_A}.digest.fail.json"
    assert json.loads(path.read_text(encoding="utf-8"))["endpoint"] == "https://provider.example/v1"
    assert store.done() == {SHA_A}


def test_done_is_per_stage(tmp_path: Path):
    StageStore(tmp_path, "triage").put(SHA_A, {})
    StageStore(tmp_path, "triage").put_failure(SHA_B, _marker())
    assert StageStore(tmp_path, "digest").done() == set()


def test_done_ignores_stray_files(tmp_path: Path):
    shard = tmp_path / "aa"
    shard.mkdir()
    (shard / f".{SHA_A}.digest.json.123.tmp").write_text("{}")
    (shard / "notes.txt").write_text("")
    (tmp_path / f"{SHA_A}.digest.json").write_text("{}")  # not in a shard
    assert StageStore(tmp_path, "digest").done() == set()


# records (SL-008) ------------------------------------------------------------


def test_records_yields_each_record_and_skips_markers_and_stray_files(tmp_path: Path):
    store = StageStore(tmp_path, "digest")
    store.put(SHA_A, {"summary": "a"})
    store.put_failure(SHA_B, _marker())
    StageStore(tmp_path, "triage").put(SHA_B, {})
    (tmp_path / "aa" / f".{SHA_B}.digest.json.123.tmp").write_text("{}")
    assert list(store.records()) == [(SHA_A, {"summary": "a"})]


def test_records_yields_none_for_unreadable_or_non_object_files(tmp_path: Path):
    shard = tmp_path / "aa"
    shard.mkdir()
    (shard / f"{SHA_A}.digest.json").write_text("{not json")
    (shard / f"{'a' * 63}c.digest.json").write_text("[1]")
    assert sorted(StageStore(tmp_path, "digest").records()) == [
        (SHA_A, None),
        ("a" * 63 + "c", None),
    ]
