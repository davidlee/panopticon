@AGENTS.md

---

**Use pi agents for delegation in this repo — not `claude -p`, not Claude subagents.**

pi on deepseek is ~20× cheaper than Claude. Keep your context for judgement.
This section lives in CLAUDE.md, not AGENTS.md, so pi workers (which read
AGENTS.md) never see it and cannot recurse.

**Key.** Host `pi` reads the gateway key from `$LLM_GATEWAY_KEY`
(`~/.pi/agent/models.json`, provider `llm-gateway`). Prefix every call:

```bash
LLM_GATEWAY_KEY=$(cat ~/.config/llm-gateway/keys/pi) <script> …
```

**Recon and judgement (plan)** — one-shot `--print`, answer on stdout:

```bash
export PI_MODEL=llm-gateway/deepseek-flash   # the profile names a jail-side model
./scripts/pi-scout "trace every caller of X"                 # structure; no thinking
./scripts/pi-research "does SL-006 I2 cover this new path?"  # judgement; thinking low
```

Prompt on argv or stdin; `PI_BACKSTOP` seconds hard cap (default 900). Their
tools include `bash`: give them read-only questions. Profiles: `.pi/agents/`.

**Execute** — a confined worker in a fresh worktree fork. It writes only
inside the fork and hands back an **uncommitted** delta; review it, run
`just check`, and commit on `main` yourself:

```bash
./scripts/spawn-confined.sh pi "$(git rev-parse HEAD)" wk/sl-NNN-phase-NN \
  .worktrees/sl-NNN-phase-NN prompt.md [BACKSTOP_SECS]
```

The prompt file must carry everything: the phase objective, criteria, files,
and how to run tests in the fork. `PI_THINKING` (default `off`; use `high` for
implementation). Remove the worktree after landing the delta.

**Review** — confined, read-only (the whole fs is ro except `~/.pi` and the
out dir). The prompt must tell the reviewer to write `<OUT_DIR>/<LABEL>.md`:

```bash
./scripts/pi-review.sh <LABEL> prompt.md <OUT_DIR> [BACKSTOP_SECS]
```

`PI_THINKING` defaults to `low`. Model: pi's default (`~/.pi/agent/settings.json`).

**Reports.** `spawn-confined.sh` reduces the worker's event stream with
`bin/pi-run-reduce` (`pi/reduce/`, TS run by node ≥ 22.6). Tests:
`scripts/lib/pi-report-test.sh`, `node --test pi/reduce/reduce.test.ts`.

**`jailed-pi`** (`PI_BIN=jailed-pi`) currently fails here: `.envrc`'s
`JAIL_WORKSPACE_DEPS` names `~/.emacs.d`, which no longer exists, and the
devshell bakes it into the jail at evaluation.

Traps (raw `pi` runs):
- `--mode rpc` is **not** a one-shot: it exits on stdin EOF without answering.
  The scripts hold stdin open with a fifo and reap on completion.
- json mode exits 0 even when the model errored; trust the reducer's verdict.
- Leave `--no-extensions` in, or the child loads the doctrine pi extension and
  rewrites `.doctrine/state/boot.md`.
- `--tools` *replaces* the tool set: name every tool you want.

Scripts and reducer copied from `~/dev/satan` (2026-10-21); fixes there do not
propagate.
