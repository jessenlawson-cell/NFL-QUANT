# NFL Quant Evidence-Interface Pivot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop new predictive scoring while preserving automated evidence capture and deliver a verified, current read-only brief for the ChatGPT NFL interface.

**Architecture:** Reuse the existing idempotent odds snapshot and scheduled slots, but remove model calls from their execution path. Export selected snapshot evidence through a separate read-only Python command; ChatGPT reads that export under a new analysis contract, while frozen model artifacts remain untouched historical records.

**Tech Stack:** Python 3, Typer, SQLite, Polars/Pandas, pytest, PowerShell Task Scheduler, Docker Compose, ChatGPT Work or explicit Project upload.

**Spec:** `docs/superpowers/specs/2026-09-27-nfl-quant-evidence-interface-pivot-design.md`

## Global Constraints

- Weekly Codex used percentage must remain below 41%; check after each task and stop at the threshold.
- Make no provider call during tests, preflight, or cutover verification. Preserve one-call-per-slot reservation and no automatic retry.
- Do not modify frozen model binaries, model specifications, old predictions, or historical evidence. Preserve the user's unrelated `market_odds.csv` edit.
- Monday-night priority: capture-only schedule first; interface/export second; documentation cleanup last. Never claim the actual Monday capture happened before it does.
- No claimed validated edge, staking, bankroll, Kelly, or automated betting. All dataset-derived numerical claims require dataframe/Python execution.

## File responsibilities

- `src/nfl_bets/pilot.py`: expose model-independent `preflight_capture` by sharing the existing runtime/quota/duplicate checks, without changing legacy `preflight_pilot` semantics.
- `src/nfl_bets/cli.py`: add `pilot preflight-capture` as a zero-credit command; retain `odds snapshot` as the only scheduled capture command.
- `scripts/run_scheduled_slot.ps1`: route old scheduled task actions to preflight-capture then odds snapshot, never pilot capture.
- `scripts/finalize_pilot_tasks.ps1`, `scripts/install_pilot_tasks_once.ps1`, `scripts/install_scheduled_tasks.ps1`: install data-only recurring capture after the one-time pilot, never model-linked recurring jobs; prevent reinstalling the old pilot.
- `scripts/run_feature_refresh.ps1`: retain source sync and validation, remove model-feature builds.
- `src/nfl_bets/interface/evidence.py`, `scripts/export_evidence_brief.py`: read-only snapshot selection, canonical-ID joins, cutoff checks, and immutable JSON/manifest export.
- `AGENTS.md`, `PROJECT_STATE.md`, `NFL_QUANT_CHATGPT_INTERFACE.md`: new repository and ChatGPT operating contract; old model specifications remain historical.
- Corresponding unit/integration tests pin each behavior.

## Review Focus

1. Already-reserved or ambiguous capture slot: preflight blocks provider contact, not a retry. Task 1 tests this.
2. Legacy finalizer fires after capture cutover: it installs data-only recurring tasks even if the old scoring pilot is incomplete, and cannot install model-linked tasks. Task 2 tests this.
3. Future-dated or overwritten injury/context records: export excludes them or marks unavailable, never backfills a pregame view. Task 3 tests this.
4. Duplicate or unmatched game/event IDs: export fails closed, not a name-based join. Task 3 tests this.
5. ChatGPT local-folder access is absent or old Project files remain: do not claim a live connection; issue an immutable upload packet and explicit replacement guidance. Task 4 tests/records this.

---

### Task 1: Capture-only scheduled path — complete before the next slot

**Files:** Modify `src/nfl_bets/pilot.py`, `src/nfl_bets/cli.py`, `scripts/run_scheduled_slot.ps1`; modify `tests/unit/test_pilot.py`, `tests/unit/test_feature_refresh_script.py`.

**Interfaces:** `preflight_capture(slot: str | None = None, settings: Settings | None = None) -> dict[str, Any]` returns the current readiness contract with no model fields/checks; CLI `pilot preflight-capture --slot SLOT` exits 2 when unsafe. Existing `odds snapshot --slot SLOT` remains the capture command.

- [ ] Write `test_capture_only_preflight_never_loads_models` and `test_capture_only_preflight_blocks_reserved_slot` in `tests/unit/test_pilot.py`, asserting `safe_to_capture`, absence of model checks, and no bundle calls. Update `test_routine_docker_stderr_does_not_abort_capture` to assert `pilot preflight-capture` then `odds snapshot`, with no `pilot capture`, `predict`, or `--shadow-version` in Docker arguments.
- [ ] Run `pytest tests/unit/test_pilot.py tests/unit/test_feature_refresh_script.py -q`; confirm the new assertions fail before the change.
- [ ] Extract shared readiness checks from `preflight_pilot`, implement `preflight_capture`, wire the CLI, and replace the runner's two Docker commands. Keep old PowerShell `-Version`/`-ShadowVersion` parameters harmless for already-installed task actions, but do not pass them to Docker.
- [ ] Run targeted tests, then `pytest tests/unit/test_pilot.py tests/unit/test_feature_refresh_script.py -q`; require pass. Run `git diff --check` and commit only Task 1 files.
- [ ] Run the new zero-credit preflight in Docker for the next unspent slot. Do not run `odds snapshot` manually. Inspect the installed task action and its next trigger; verify it points to this changed runner.

### Task 2: Close legacy model-schedule paths, retain source refresh

**Files:** Modify `scripts/finalize_pilot_tasks.ps1`, `scripts/install_pilot_tasks_once.ps1`, `scripts/install_scheduled_tasks.ps1`, `scripts/run_feature_refresh.ps1`; modify `tests/unit/test_feature_refresh_script.py`; add `tests/unit/test_schedule_sunset.py`.

**Interfaces:** Existing one-time capture task names and times stay unchanged. The Monday finalizer registers future weekly data-only capture tasks through an idempotent `install_scheduled_tasks.ps1` without requiring the old scoring-pilot report. The feature-refresh runner calls `data sync` and `validate` only.

- [ ] Add `test_refresh_only_syncs_and_validates` to `tests/unit/test_feature_refresh_script.py` and `test_finalizer_installs_data_only_schedule_without_pilot_pass` plus `test_installer_omits_model_arguments` to `tests/unit/test_schedule_sunset.py`. Assert no `challenger train`, `features build`, `pilot capture`, or model-version arguments in active recurring task actions.
- [ ] Run `pytest tests/unit/test_feature_refresh_script.py tests/unit/test_schedule_sunset.py -q`; confirm failure before the change.
- [ ] Implement the minimum script changes; inventory all current `NFL-BETS-*` task actions, disable only any separate model-training/prediction tasks not routed through Task 1, and record exact task names and prior state. Keep data-capture triggers enabled. Add a dry-run/install verification path that does not contact the provider.
- [ ] Run `pytest tests/unit/test_feature_refresh_script.py tests/unit/test_schedule_sunset.py -q` and a read-only installed-task audit; require pass, then commit Task 2 files. No provider call.

### Task 3: Immutable game evidence brief

**Files:** Create `src/nfl_bets/interface/__init__.py`, `src/nfl_bets/interface/evidence.py`, `scripts/export_evidence_brief.py`, `tests/integration/test_evidence_brief.py`.

**Interfaces:** `export_evidence_brief(snapshot_id: str, settings: Settings, generated_at_utc: str | None = None) -> dict[str, Any]` reads SQLite in read-only mode and produces one versioned JSON file plus a hash manifest under `reports/evidence_interface/` and `manifests/evidence_interface/`. CLI takes `--snapshot-id` and optional `--root`; no provider or model call.

- [ ] Write `test_export_valid_decision_brief`, `test_export_rejects_close_and_post_kickoff`, `test_export_rejects_duplicate_or_unmatched_ids`, `test_export_excludes_future_or_unverifiable_context`, and `test_export_rejects_missing_time_or_tampered_raw` in `tests/integration/test_evidence_brief.py`. Assert exact source rows, canonical joins, immutable rerun/hash, no model/prediction fields, and all named rejection cases.
- [ ] Run `pytest tests/integration/test_evidence_brief.py -q`; confirm failure before the change.
- [ ] Implement the smallest read-only query/export. Use dataframe operations for joins and diagnostics; reject ambiguous keys; exclude any context whose historical availability cannot be established. Preserve nulls and report absent coverage. Never infer an odds edge or a model probability.
- [ ] Run targeted tests and `git diff --check`; commit Task 3 files. Export one existing eligible snapshot without provider contact and verify the file/manifest hashes.

### Task 4: ChatGPT contract and end-to-end verification

**Files:** Modify `AGENTS.md`, `PROJECT_STATE.md`; create `NFL_QUANT_CHATGPT_INTERFACE.md`; add/update a focused contract test in `tests/unit/test_interface_contract.py`.

**Interfaces:** ChatGPT contract instructs one weekly chat to read the newest verified brief, ask for an as-of refresh when stale, stress-test user-proposed bets, cite exact observations, separate fact from judgment, and decline unsupported conclusions. Repository instructions no longer direct active model scoring or staking.

- [ ] Write `test_current_instructions_are_evidence_interface_only` in `tests/unit/test_interface_contract.py`. Assert `AGENTS.md` and `PROJECT_STATE.md` do not instruct active predictive scoring or staking, and `NFL_QUANT_CHATGPT_INTERFACE.md` requires source, as-of timestamp, freshness, missingness, uncertainty, and an upload fallback when local access is unavailable.
- [ ] Run `pytest tests/unit/test_interface_contract.py -q`; confirm failure before the change.
- [ ] Update the three documents; keep `MODEL_SPEC*`, `CHALLENGER_SPEC*`, old ledgers, and prior interface packets untouched and labelled historical in current guidance.
- [ ] Run unit/integration tests relevant to changed paths, `git diff --check`, and commit Task 4 files.
- [ ] Verify one actual brief is accessible in ChatGPT Work desktop with read-only folder permission if available. If not, provide the exact brief and manifest for Project upload and identify obsolete Project instructions/files for user replacement. Do not claim the external ChatGPT connection was changed without confirming it.

### Task 5: Final audit and handoff

**Files:** No additional product files; write a short status report only if needed under `reports/evidence_interface/`.

- [ ] Verify frozen artifact hashes and operational row counts against pre-cutover baselines, and inspect all upcoming scheduled actions and next run times.
- [ ] Confirm no test or audit spent an odds-provider credit; disclose any unavoidable uncertainty.
- [ ] Check weekly Codex usage; stop if 41% used or higher. Give the user the exact Monday readiness state, ChatGPT brief location, any required manual UI step, and remaining work.
