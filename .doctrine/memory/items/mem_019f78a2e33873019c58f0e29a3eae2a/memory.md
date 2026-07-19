# Conformance can lie when the source-delta registry drifts

At audit, cross-check the source-delta registry — a green suite does not imply a
truthful conformance ledger.

`doctrine slice conformance` and `slice verify-vt` read the recorded source-delta
boundaries (`.doctrine/state/slice/NNN/boundaries.toml`), **not** git directly. If
a phase's boundary is misrecorded — a zero-width range, or a range whose start OID
is another phase's real code commit — the phase's actual commit is orphaned from
every delta. The symptoms are a *lying* signal: a committed, present file reads
`undelivered`, and VT criteria backed by passing tests read `UNATTRIBUTABLE`
("not modified by this slice"), all while the suite is green.

This bites when phase commits interleave with test/chore commits (auto solo
phase-binding picks the wrong tip). Fix: re-record the phase to its real commit —
`doctrine slice record-delta <ID> PHASE-NN --commit <S>` (the safe single-commit
mode records exactly `[S^, S]`). Re-run `slice conformance` / `verify-vt` to
confirm `undelivered:0` and attributable VTs. First surfaced in SL-003 audit
(RV-003, F-1).
