# AX dogfood run playbook

> This is the version-controlled source of truth for one AX dogfood pass.
> The cron wrapper (`scripts/ax-dogfood/run.sh`) feeds this file to a headless
> `claude` session; the thin `/ax-dogfood` slash command just points here for
> interactive use. Edit THIS file to change the loop's behavior.

Mode: long-horizon dogfooding + implementation, in a single bounded pass.

Objective: Use Trade Trace exactly as a live trading bot would — through its
MCP tools, on live Polymarket data — discover every point of experience friction
(discoverability, clarity, ergonomics, correctness), then improve the system:
fix bugs and friction directly with atomic commits, and file genuinely new
features / major reworks to Beads.

You are Claude Code running in the repo `/home/hermes/code/trade-trace`, on the
`ax-dogfood` branch, with the `trade-trace` MCP server connected (actor
`agent:ax-dogfood`, journal home `~/.trade-trace-axloop`, live Polymarket
enabled). The full design is `docs/ax-dogfood/2026-06-03-ax-dogfood-loop-design.md`
— read it if you need rationale.

## Ground rules (read first, they bound everything below)

- **Never push `main`. Never tag or publish.** All work lands on `ax-dogfood`
  and goes to `main` only through the standing PR that the human merges.
  Pushing `main` auto-publishes to PyPI — do not do it.
- **Contract firewall:** never directly edit append-only writes, idempotency
  enforcement, the typed envelope contract, or the single-writer model. Those
  are always Beads items, never direct fixes.
- **Honesty:** never weaken, skip, `xfail`, or delete a test to make a fix pass.
  If a fix can't pass the gates, revert it and file a bead. In the run report,
  separate *fixed & gate-verified* from *filed* from *attempted-then-reverted* —
  never round up.
- **Secret hygiene:** Gamma is a public API (no secrets), but still never paste
  raw response bodies, tokens, or env contents into the run report — record
  IDs, fields, and booleans only.
- **Bounded pass:** this is ONE lifecycle pass (a handful of markets, ~2–4
  forecasts), not an exhaustive sweep. Depth over breadth.

First, confirm you are on the right branch; if not, STOP and write a failure
note instead of operating on the wrong branch:

```bash
git rev-parse --abbrev-ref HEAD   # must print: ax-dogfood
```

---

## Phase A — Sync & orient (as a dev)

1. `git fetch origin && git rebase origin/main`. If the rebase conflicts:
   `git rebase --abort`, log "rebase skipped (conflict)" for the run report, and
   continue on the un-rebased branch — never block the run on this.
2. Read `docs/ax-dogfood/registry.md` (rolling friction registry) and
   `docs/ax-dogfood/intentional-design.md` (do-not-fix list). You will NOT
   re-report or re-fix anything already in those files. Behaviors in the
   intentional-design list are deliberate — if one still impedes a real bot,
   file a Beads *question*, do not change it.
3. **Load the open bead queue (dedup context).** Run
   `bd list --status open --label ax-dogfood` and `bd ready`, and read the
   open friction beads. The loop fires hourly, so duplicate filings are the
   main backlog-noise risk — hold this list in mind so that anything you file
   in Phase C is compared against what already exists, not just keyword-matched.
4. Establish a run id: `date -u +%Y-%m-%d-%H%M` (call it `RUN_ID`). Use the date
   part for the run-report filename `docs/ax-dogfood/runs/YYYY-MM-DD-NN.md`,
   where `NN` is the next free 2-digit sequence for today.

---

## Phase B — Be the trading bot (as a user, COLD)

**Discipline: in this phase you are a bot, not an engineer. Use ONLY the
trade-trace MCP tools, `tool.schema`, and `docs/AGENT_GUIDE.md`. Do NOT open
`src/` or read implementation code in this phase — your confusion is the signal
we are collecting.** Keep a running friction log as you go: for each rough edge,
note the surface (tool / schema text / error message / doc / report / onboarding),
what you expected, what happened, and why it slowed you down.

Drive the canonical journal loop (follow `docs/AGENT_GUIDE.md`; introspect any
unfamiliar tool with `tool.schema` first):

1. **Orient:** `report.bootstrap`, then the process reads it suggests
   (`report.work_queue`, `report.lifecycle`, `report.recall_receipts`). Ask
   yourself: as a bot, do I actually know what to do next from this?
2. **Resolve what's due:** for each of your own open forecasts whose market may
   have closed, determine the true outcome (see *Resolution determination*
   below) and record it via `resolution.add`.
3. **Scan & forecast:** fetch live Polymarket markets, pick 2–4 binary ones,
   `market.bind` each (binary only — >2 outcomes is rejected by design),
   `snapshot.fetch` or `snapshot.add`, `memory.recall` prior lessons, form a
   thesis, then `forecast.add` with an explicit probability and `confidence`.
   Then record a `decision.add` (use `paper_enter` to open a paper position).
4. **Review:** `report.calibration`, `report.coach`, and any process report. As
   a bot, is this feedback actually useful and actionable to me?
5. **Remember:** `memory.retain` / `memory.reflect` a lesson; `memory.recall` to
   confirm it round-trips.

**Ordering prereqs to honor (not friction — real constraints):** bind a market
before forecasting it; a scoreable forecast must already exist before a
resolution can auto-score it.

**Idempotency:** supply an explicit `idempotency_key` on every retryable write,
formatted `axloop:<RUN_ID>:<short-purpose>` (e.g. `axloop:2026-06-04-0900:fc-elec`).
This keeps replays clean and writes legible.

**Resolution determination (faithful, never fabricated):** for a closed market,
inspect the adapter's raw fields. If `winningOutcome` is present → record
`resolution.add` with that binary label, `status=resolved_final`,
`confidence=0.99`. If there's no `winningOutcome` but `outcomePrices` are
unambiguous (one side ≈ 1.0) → record with `confidence ≥ 0.9`. If it's genuinely
ambiguous, you may do light web research; if still uncertain, **leave the
forecast open and log it as friction** — do NOT invent an outcome and do NOT set
`confidence` to 0.9 just to satisfy the auto-score gate. `confidence` must
reflect your genuine certainty.

6. **Cold-start probe:** spend a few minutes onboarding a throwaway journal from
   scratch to re-probe first-run friction, then destroy it:
   ```bash
   AXPROBE="/tmp/tt-axprobe-$(date -u +%s)"
   TRADE_TRACE_HOME="$AXPROBE" tt journal init
   TRADE_TRACE_HOME="$AXPROBE" tt report bootstrap --as-of "$(date -u +%FT%TZ)" --filter-json '{}'
   # ...note onboarding friction a brand-new bot would hit...
   rm -rf "$AXPROBE"
   ```

---

## Phase C — Improve what hurt (as an engineer, INFORMED)

Now you may read source freely. Triage every friction item from Phase B:

- **Fix directly** (bug, confusing schema/error/`next_actions` text, doc drift,
  small ergonomics): make the smallest sufficient change, each as its own
  **atomic commit** with a conventional message that references the friction.
  Add or update a regression test where it makes sense. Run `ruff check src tests`
  + `mypy src` + the targeted tests for what you touched before each commit.
  - The `trade-trace` MCP server is a long-lived process for this session, so a
    tool-code fix does NOT take effect in the live MCP tools until a **fresh
    session** boots a new server (a cron `run.sh` fire, or a restarted `/loop`
    session — NOT the next `/loop` iteration in this same session). Verify such
    fixes with a unit test and note "effective next fresh session"; do not fight
    to hot-reload the server, and do not be surprised if the live MCP still shows
    old behavior this session.
- **File to Beads** (genuinely new tool/feature, major or cross-cutting rework,
  contract-firewall item, or anything ambiguous/design-level): first **dedup
  against the open queue you loaded in Phase A** — compare your finding to those
  open `ax-dogfood` beads *and* run `bd search <keywords>`. If a bead already
  covers it (even under different wording), append your new evidence to it with
  `bd update <id> --notes="..."` instead of filing a new one. Only when nothing
  matches, `bd create --type=... --label=ax-dogfood` with the friction evidence
  in the description. For intentional-but-confusing behavior, file it as a
  *question*.
- If a fix fails the gates and you can't make it pass honestly, `git revert` /
  discard it and file a bead instead.

---

## Phase D — Close out

1. **Gate:** run the full suite once — `ruff check src tests`, `mypy src`,
   `pytest -q`. The branch only pushes if green. If a pre-existing (not
   yours) failure blocks the suite, stop, capture it, and report it rather than
   pushing unrelated breakage forward.
2. **Write the run report** `docs/ax-dogfood/runs/YYYY-MM-DD-NN.md`:
   - friction found (with surface + severity),
   - fixes made (with commit SHAs), beads filed (with ids),
   - attempted-then-reverted items,
   - gate results (exact pass/fail counts),
   - handoff notes for the next run.
3. **Update `docs/ax-dogfood/registry.md`**: add/update one row per
   friction item with its disposition (open/fixed/filed/intentional). Promote
   any newly-confirmed intentional behavior into `intentional-design.md`.
4. **Commit & push:** commit the run report + registry update, then
   `git push -u origin ax-dogfood`. Open or refresh the standing PR to `main`:
   `gh pr list --head ax-dogfood` → if none, `gh pr create --base main --head
   ax-dogfood --title "AX dogfood: rolling fixes" --body "<summary>"`; otherwise
   `gh pr edit` / push updates the existing PR. **Do not merge it.**
5. **Verify safety:** confirm no commit landed on `main`
   (`git log origin/main..HEAD --oneline` is your branch's commits only) and
   that you never pushed `main`.

## Final output (print to the session)

- Summary (one paragraph): what you exercised, how it felt as a bot.
- Friction found: count + the headline items.
- Fixes: list with SHAs. Beads filed: list with ids. Reverted: list.
- Gate result: exact `pytest` summary line.
- Run report path. Branch/PR status. Anything left for the human.

## Stop / escalate

- Wrong branch, can't init the journal, or git in a broken state → STOP, write a
  short failure note to the run report, do not improvise around it.
- A friction item is a *finding*, not a stop condition — capture it and keep
  going. Only halt for environment/safety problems, never because the system
  behaved badly (that's the point).
