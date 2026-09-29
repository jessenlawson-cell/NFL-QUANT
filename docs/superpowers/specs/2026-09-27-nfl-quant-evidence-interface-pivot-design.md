# NFL Quant evidence-interface pivot — design

Date: 2026-09-27  
Status: proposed for user review; not implementation authorization

## Intent and scope

End new predictive-model scoring, training, challenger ablations, and the
Week 3–8 model-efficiency program. Preserve all historical inputs, snapshots,
model artifacts, predictions, and audit records without rewriting or deleting
them. Keep collecting timestamped football and market evidence. Make ChatGPT
the day-to-day interface for asking whether a proposed NFL bet withstands a
source-grounded stress test. The user supplies a natural-language question;
the interface can retrieve a verified price and context, explain for/against
evidence, uncertainty, and possible alternatives. It must not claim a proven
predictive edge or invent missing calculations. No staking, bankroll, Kelly,
or automated betting.

The repository remains the canonical evidence and rule store; Codex builds,
tests, and maintains it. ChatGPT does not mutate the repository. Analysis is
not a continuation of either frozen model's recommendation. Those models stay
historical and unmodified, with their recorded PASS decisions intact.

## Approach and deadline

Recommended: staged cutover before Monday night football. First decouple the
existing scheduled capture from predictive scoring, verify a capture-only
Monday path, and produce a timestamped read-only game evidence brief. Then
update the repo's primary instructions and ChatGPT Project guidance, test the
ChatGPT access path, and retire unneeded predictive schedules safely.

Rejected for this deadline: a full rewrite of the ingestion system, because
it creates a new failure mode before Monday. Manual ChatGPT uploads alone are
a fallback, not a live-sync architecture: uploads go stale and do not validate
themselves. The prior one-way model-output packet remains historical; it must
not become the new interface's authority for current advice.

## Data flow and boundaries

1. A scheduled, idempotent capture obtains the registered odds snapshot with
   its original slot purpose and provenance. A zero-credit preflight checks
   schedule, duplicate/reservation state, runtime, and quota before provider
   contact. It does not load model artifacts or invoke model prediction.
2. A read-only evidence builder selects a specific snapshot and joins only
   canonical game/team identifiers to football context available by the
   requested as-of time. It records source, retrieval time, availability time,
   schema/hash, freshness, missingness, and coverage. Post-decision or
   ambiguous inputs remain excluded/null. No free-text name joins.
3. It emits a compact, versioned evidence brief for the requested game and
   market, including the exact quote and time, material injuries/availability,
   relevant team context, conflicts, and uncertainty. Calculations occur in
   Python/dataframes, not prose. No fabricated probability or positive-EV
   claim where validated probability is unavailable.
4. ChatGPT Work desktop may read only the evidence brief and selected rule
   files locally, if that account's local-folder access is enabled. If not,
   an explicit upload of the same immutable brief to the existing ChatGPT
   Project is the deadline fallback. GitHub access is only for pushed files;
   it is not a substitute for current local-only data.

## Operational cutover

- Inventory every existing task and its trigger/action. Change only tasks
  whose current action scores or trains a predictive model; preserve capture
  slots needed for fresh evidence. Never blanket-disable all tasks.
- Do not spend an odds-provider call while testing. Use mocks and existing
  snapshots. Before the Monday slot, verify the zero-credit preflight and
  capture-only command without making a provider request.
- Existing ledgers and model artifacts remain append-only historical records.
  Do not rewrite a PASS row into an active recommendation. Mark old model
  documentation as historical and replace conflicting top-level operating
  instructions with the new interface contract only after the capture path
  is verified.
- If a cutover check fails, fail closed and disclose that fresh evidence is
  unavailable; do not silently fall back to a stale snapshot. Restore the
  last known data-capture schedule only when that can be done without
  re-enabling predictive scoring.

## Acceptance and verification

- Tests prove DECISION and CLOSE capture paths do not call either scorer;
  duplicate and quota controls still prevent automatic extra provider calls.
- Verify scheduled task actions and next run times, a dry-run preflight, and
  a mock capture. Compare operational row counts and frozen artifact hashes
  before/after the dry run. Do not claim a live Monday capture succeeded
  before it actually occurs.
- Test evidence-brief rejection of stale, future-dated, duplicate, unmatched,
  and post-kickoff inputs. ChatGPT must state exact as-of time, cite the brief,
  separate observed fact from judgment, and say when evidence is insufficient.
- Verify the ChatGPT access method with one actual brief before calling the
  interface ready. If account/UI access is unavailable, hand off the brief
  and concise upload instructions rather than asserting a connection exists.

## Usage ceiling

The weekly Codex usage reading was 21% before this pivot. Stop pivot work at
41% weekly used, checking after meaningful milestones. This is a usage ceiling,
not a prediction of cost or a guarantee the full cutover will fit beneath it.
