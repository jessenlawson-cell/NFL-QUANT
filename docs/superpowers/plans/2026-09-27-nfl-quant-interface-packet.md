# NFL QUANT Interface Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a small, immutable, snapshot-specific packet that lets a weekly ChatGPT chat interpret persisted frozen predictions without changing the PASS-only evidence engine.

**Architecture:** A standalone script outside `src/` reads the operational SQLite database in read-only mode, validates one completed DECISION snapshot and its persisted predictions, and atomically publishes one JSON packet plus a hash manifest. Separate Project instructions specify how ChatGPT may derive clearly labelled exploratory interpretations from those outputs; no scorer or provider is invoked.

**Tech Stack:** Python 3.13, SQLite, JSON, pytest, Docker Compose, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-09-27-nfl-quant-interface-design.md`

## Global Constraints

- Do not modify `src/`, frozen specifications, model artifacts, scheduled-task scripts, operational SQLite tables, or CSV ledgers. Keeping the exporter under `scripts/` also avoids dirtying protected `src/` while scheduled preflights run.
- Export one validated, pre-kickoff `DECISION` snapshot at a time. No provider or nflreadpy call; no train, predict, settle, or compare call.
- The only writes are versioned `reports/interface/` and `manifests/interface/` packets, plus the new exporter, tests, and Project handoff documentation.
- Preserve both model versions and all stored `PASS` decisions. `challenger-0.3.0` remains `RESEARCH_ONLY_UNWEIGHTED`; omit it from the first packet because no captured research evidence is available.
- Never export CLOSE quotes, final scores, results, CLV, settled performance, Kelly, stakes, bankroll, or active risk values. Do not upload provider-derived quote content until its sharing rights are confirmed.
- Missing probabilities are valid on ineligible persisted rows: retain the row and exclusion reason, but never use it for an exploratory side.

## Review Focus

1. An ineligible prediction has null market/probability fields: retain it with its reason, never make a side suggestion (Task 1 test).
2. A concurrent scheduled capture is writing SQLite: a read-only transaction must see one consistent snapshot; publication fails closed if protected state changes during export (Task 1 and Task 2 tests).
3. A snapshot is complete but its challenger report has the wrong ID or is absent: fail without publishing (Task 1 test).
4. A packet already exists for the same snapshot/version: verify identical bytes or fail; never overwrite changed evidence (Task 2 test).
5. Model and market probabilities are compared at different push bases: use calibrated non-push probability against proportional no-vig probability, never `model_win_probability` directly (Task 3 test).

---

## File map

- Create `scripts/export_interface_packet.py`: read-only selection, provenance checks, packet serialization, and an explicit `--snapshot-id` CLI. No imports into production code.
- Create `tests/integration/test_interface_packet.py`: isolated SQLite fixture, failure sentinels, immutability, and operational-state assertions.
- Create `docs/interface/NFL_QUANT_PROJECT_INSTRUCTIONS.md`: copyable Project instruction text under 8,000 characters.
- Create `docs/interface/WEEKLY_PROMPT.md`: one weekly chat kickoff prompt and upload checklist.
- Runtime outputs only: `reports/interface/<season>-W<week>/<snapshot_id>.json` and matching `manifests/interface/<season>-W<week>/<snapshot_id>.json`.

### Task 1: Read-only snapshot validation and row selection

**Files:** Create `scripts/export_interface_packet.py`; test in `tests/integration/test_interface_packet.py`.

**Interfaces:** Produce `load_validated_snapshot(db_path: Path, root: Path, snapshot_id: str) -> dict[str, Any]`. It returns the snapshot metadata, two frozen policy identities, scoreless game identifiers, persisted prediction rows, and matching challenger report metadata. It never creates or migrates a database.

- [ ] **Step 1: Write failing fixture tests.** Initialize only a temporary test database with the existing schema. Insert one complete DECISION snapshot, one valid game, both versions' PASS predictions, and a matching challenger report. Assert `load_validated_snapshot(...)` returns exactly those rows and no outcome fields. Add tests for ineligible null rows, wrong/missing report, CLOSE purpose, incomplete request, duplicate game-market-version, post-decision quote, feature as-of at/after decision, prediction at/after kickoff, future outcome sentinel, and invalid snapshot ID.
- [ ] **Step 2: Run the focused tests and confirm failure.** Run `docker compose run --rm --entrypoint python nfl-bets -m pytest tests/integration/test_interface_packet.py -q`. Expected: missing exporter/interface failures, not provider contact.
- [ ] **Step 3: Implement the loader.** Open `db_path.resolve().as_uri() + '?mode=ro'` with `sqlite3` URI and `PRAGMA query_only=ON`; use one explicit read transaction. Validate snapshot raw-file content hash, `api_requests.status='COMPLETE'`, `snapshot_purpose='DECISION'`, required prediction keys, policy/hash identity, source availability and strict chronology. Select rows by exact snapshot ID and model versions; join games only by `game_id`. Retain excluded rows with nulls and reasons; require complete numbers only for rows eligible for interpretation. Cross-check the challenger report's snapshot ID and time.
- [ ] **Step 4: Re-run the focused tests.** Expected: all Task 1 cases pass, no operational write, no provider call.
- [ ] **Step 5: Commit only the exporter and fixture tests.** Do not stage changing capture ledgers or reports.

### Task 2: Immutable packet, manifest, and explicit CLI

**Files:** Extend `scripts/export_interface_packet.py` and `tests/integration/test_interface_packet.py`.

**Interfaces:** Produce `build_packet(source: dict[str, Any], generated_at_utc: str) -> dict[str, Any]` and `publish_packet(packet: dict[str, Any], root: Path) -> tuple[Path, Path]`. CLI accepts `--snapshot-id` only, derives output paths from validated season/week and UUID, and prints paths plus hashes.

- [ ] **Step 1: Write failing packet tests.** Assert schema/version and required UTC/hash fields, separate 1.1.2 and challenger rows, unchanged PASS decisions, scoreless game mapping, absent banned fields, and the SHA-256 manifest. Assert same-ID rerun leaves bytes and timestamps untouched, different bytes fail, and an exception leaves no completed manifest. Assert unchanged protected hashes and row counts in a quiescent test; a concurrent fixture write must produce a consistent read but block publication rather than be attributed to the exporter.
- [ ] **Step 2: Run the focused tests and confirm failure.** Use the Task 1 pytest command; expected failures are missing packet functions.
- [ ] **Step 3: Implement deterministic publication.** Serialize sorted-key UTF-8 JSON. On first publication set `generated_at_utc`; on rerun reuse the recorded value and byte-compare rather than overwrite. Measure protected hashes and operational counts before and after source selection; fail closed if they change. Write temporary files under the two dedicated output roots, verify hashes, then rename packet and finally manifest. The manifest is the completion marker; any orphan packet without it is ignored. Reject existing differing content. Do not use `pilot_status()` because it writes a report.
- [ ] **Step 4: Re-run focused tests, Ruff, and mypy.** Run `docker compose run --rm --entrypoint python nfl-bets -m pytest tests/integration/test_interface_packet.py -q`; `docker compose run --rm --entrypoint ruff nfl-bets check scripts/export_interface_packet.py tests/integration/test_interface_packet.py`; and `docker compose run --rm --entrypoint mypy nfl-bets scripts/export_interface_packet.py`. Expected: all pass.
- [ ] **Step 5: Commit only Task 2 files.** Leave operational evidence unchanged.

### Task 3: Project instructions and Week 3 handoff

**Files:** Create `docs/interface/NFL_QUANT_PROJECT_INSTRUCTIONS.md` and `docs/interface/WEEKLY_PROMPT.md`; test relevant instruction rules in `tests/integration/test_interface_packet.py`.

**Interfaces:** The weekly chat consumes only one or more validated packets and the already uploaded frozen specs/code. Its outputs separate `Frozen model record` from `Exploratory interface interpretation`.

- [ ] **Step 1: Write failing documentation-contract tests.** Assert the Project instructions are fewer than 8,000 Python characters; require the phrases `PASS`, `RESEARCH_ONLY_UNWEIGHTED`, `snapshot_id`, `Python`, and `no model rerun`. Assert the exploratory ordering names `calibrated_non_push_win_probability` and `pinnacle_orientation_no_vig_probability` and forbids direct comparison with `model_win_probability`. Assert the weekly prompt requires a packet and an as-of cutoff.
- [ ] **Step 2: Run the focused tests and confirm failure.** Expected: missing files.
- [ ] **Step 3: Write the two documents.** The Project instruction must use only persisted weighted 1.1.2/0.2.0 predictions, validate joins and time with Python, and never attribute an interface suggestion to an official model decision. If stored `SHADOW_CANDIDATE` entries exist, present them as such. Otherwise, among rows with `eligibility_status='SHADOW_ELIGIBLE'`, valid matched prices, and valid calibrated non-push probabilities, permit an explicitly exploratory directional ordering by `abs(calibrated_non_push_win_probability - pinnacle_orientation_no_vig_probability)`; positive difference points to the recorded orientation, negative to its opposite. State that this divergence is not validated edge or a wager decision. A missing or failed gate yields no suggestion. Keep 0.3 diagnostics separate and unweighted; no internet narratives, money, stakes, or Week 3–8 outcome evaluation.
- [ ] **Step 4: Run documentation tests and Python character count.** Expected: all pass and instruction body under 8,000 characters.
- [ ] **Step 5: Commit only the two documents and their contract tests.**

### Task 4: Week 3 packet and non-interference check

**Files:** Generate only versioned runtime outputs under `reports/interface/` and `manifests/interface/`; no source changes.

**Interfaces:** Run `docker compose run --rm --entrypoint python nfl-bets scripts/export_interface_packet.py --snapshot-id <validated-DECISION-UUID>` after the scheduled capture completes and passes audit.

- [ ] **Step 1: Confirm the selected Week 3 capture passed and predates kickoff.** Use read-only database queries and the scheduled task result; do not run a capture or select a CLOSE snapshot. If not valid, stop.
- [ ] **Step 2: Record baseline model/spec/artifact hashes, operational database row counts, and frozen preflight.** Run zero-credit preflight for the next still-future slot only; do not run it on an already completed slot. Store check results outside operational state.
- [ ] **Step 3: Run the exporter once for the explicit snapshot ID.** Expected: one JSON packet and one hash manifest; no provider request.
- [ ] **Step 4: Verify packet and non-interference.** Load packet with Python, check version/status/timestamps/duplicate keys, compare pre/post protected hashes and database row counts, and rerun zero-credit preflight if a future slot exists. No differences in protected state; no new api_request; official decisions all PASS.
- [ ] **Step 5: Hand off the packet path, Project instructions, and weekly prompt.** The user confirms data-sharing rights before uploading any provider-derived quote. Do not upload files on the user's behalf.

## Plan completion gate

Run the full Docker pytest suite, Ruff, and strict mypy; inspect `git diff` for only the intended exporter/tests/docs and packet outputs. Confirm frozen `1.1.2` and `challenger-0.2.0` identities, the ongoing pilot task schedule, and operational row counts remained unchanged. Report any missing Week 3 packet as a blocker, not a backfilled substitute.
