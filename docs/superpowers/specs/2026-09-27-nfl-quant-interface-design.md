# NFL QUANT interface packet — design

Date: 2026-09-27
Status: proposed for user review; no exporter or ChatGPT instruction change is authorized by this document alone.

## Intent

Codex keeps the repository as the evidence engine. Frozen `1.1.2` and
`challenger-0.2.0` continue their existing PASS-only Week 3–8 capture and
evaluation program. A separate ChatGPT Project receives a point-in-time,
read-only packet for each weekly chat so it can interpret persisted model
outputs and discuss exploratory model-derived suggestions without rerunning,
retraining, or changing either model. The interface cannot present its own
suggestion as an official model decision or validated market edge.

Success means a user can ask what a frozen prediction says, what data and
price it used, and why a model-derived interpretation is tentative. The
answer must come from the packet and the already uploaded specifications and
source code, never from team-name narratives or unverified web commentary.

## Choice of approach

Use an **on-demand, one-way exporter** after an existing DECISION capture has
completed and passed the pilot audit. This is the first release because it
does not add a failure mode to a scheduled capture. A capture-task hook would
be more automatic but could delay or fail the evidence run; defer it. Raw
ledger uploads are simpler mechanically but mix snapshots and can disclose
post-decision data; reject them as the routine interface.

## Isolation contract

- The exporter reads existing operational evidence but never writes to the
  operational SQLite database, CSV ledgers, feature stores, model artifacts,
  frozen specifications, or scheduled-task definitions. It makes no provider
  or nflreadpy calls and does not invoke a scorer, trainer, settlement, or
  prospective comparison.
- It writes only versioned files under `reports/interface/` and
  `manifests/interface/`. A packet is immutable once published; the same
  snapshot and exporter version may be rerun only to verify byte-identical
  output. A changed packet gets a new version and preserves the old one.
- `1.1.2` and `challenger-0.2.0` remain separate lanes with their recorded
  model, artifact, policy, specification, feature-input, and Git identities.
  Their recorded decision remains `PASS` in every exported row.
- `challenger-0.3.0` has no model score or weight. Its diagnostics can be
  attached only in a separate `research_diagnostics` section when a captured
  source was available before the decision. Null, ambiguous, or backfilled
  evidence is not converted into a model input or prospective signal.
- Interface analysis and any user action based on it never feed back into
  capture selection, source data, model fitting, candidate thresholds, or
  Week 8 evaluation. Prospective outcomes and comparator results remain
  sealed under the current policies.

## Packet flow and contents

1. The user or Codex chooses one validated, pre-kickoff DECISION snapshot ID.
   The exporter verifies the raw snapshot purpose, complete request status,
   intact source, matching challenger report, and official/challenger policy
   identities. A CLOSE or DIAGNOSTIC snapshot is rejected.
2. In a consistent read-only database transaction, select only predictions
   for that snapshot and both frozen versions, plus their recorded canonical
   market contracts. Cross-check source rows against the immutable snapshot
   and report. Do not use a later market quote, injury update, result, or
   closing line to explain a DECISION.
3. Join scoreless game metadata by `game_id` only. Export kickoff, home and
   away team identifiers for display, but no final scores or result fields.
   Keep the original prediction orientation, market, line, paired prices,
   model win/push/loss probabilities, projections, eligibility, uncertainty,
   pass reason, and any stored shadow label. A human-readable name is never
   used as a join key.
4. Include packet version, generated-at UTC, decision and feature as-of UTC,
   quote-update UTC, model and source hashes, row counts, duplicate/unmatched
   diagnostics, source-file identities, and a packet content hash. The packet
   names the exact snapshot and states that all official decisions are PASS.
5. Publish one small JSON packet and its manifest atomically after all
   checks pass. Do not upload the whole changing prediction or odds ledgers.
   Provider quote content is limited to the matched contracts already used
   by the persisted predictions; data-sharing rights must be checked before
   any upload outside the repository.

The first release exports the frozen outputs and existing diagnostics, not a
new explanation score. It may describe observed input values and frozen
model outputs, but cannot invent per-game feature contributions from model
code alone. A later explanation method would require its own provenance and
validation; it is not part of this design.

## ChatGPT Project contract

Use one chat per NFL week and upload only the relevant validated packet(s).
The Project's static specifications explain the equations; the packet is the
sole authority for a current numerical claim. ChatGPT runs Python/Pandas or
Polars for every dataset-derived calculation, verifies key uniqueness and
timestamp cutoffs, and fails closed on missing or conflicting evidence. It
does not claim to run the frozen models.

The response has two explicitly separated parts:

1. **Frozen model record:** persisted projections, probabilities, market
   comparison, eligibility, and official `PASS` decision, attributed to the
   exact snapshot and version.
2. **Exploratory interface interpretation:** an optional, clearly labelled
   discussion of possible sides using only those persisted outputs and the
   repository's documented quantitative mechanics. This is neither a model
   decision nor an input to prospective evaluation. No stake, bankroll,
   Kelly value, active risk value, or claim of proven betting performance is
   produced. If the validated data supports no suggestion, say so.

The Project instructions must be updated separately to express this two-part
contract. Merely removing money language from the old instructions is not
enough: the old `top bets` prohibition and the distinction between a model
decision and interface interpretation must be handled explicitly. Avoid
internet-driven football narratives; external data may be considered only
through a separately captured, timestamped, governed source, not ad hoc chat
retrieval.

## Fail-closed checks and acceptance

- Reject missing or duplicate snapshot, game-market-version, or quote keys;
  mismatched policy/artifact hashes; stale or post-decision quotes; feature
  timestamps not strictly before the decision; predictions at or after
  kickoff; missing required probabilities; ambiguous joins; and schema
  drift. Preserve nulls and report exclusions rather than filling zeros.
- Sentinel tests place future-dated odds, feature, and outcome rows in source
  fixtures; none may enter a packet. If optional research diagnostics are
  added later, test future-dated injury and depth-chart rows too. Test that
  a CLOSE snapshot, wrong report, or incomplete request cannot be exported.
- Capture hashes and operational row counts before and after export; they
  must be identical. Import-boundary tests ensure production and challenger
  capture/scoring modules do not import the interface exporter.
- Confirm one packet can be generated and read in a fresh weekly ChatGPT chat
  before kickoff without altering a scheduled task or making a paid call.
  If a validated snapshot or upload-rights check is unavailable, report the
  blocker and leave the pilot untouched.

## Release sequence

First implement and test the on-demand exporter and a single Week 3 packet.
Then supply the revised Project instructions and a weekly kickoff prompt that
names the packet's snapshot ID. The user uploads that packet manually. Keep
the exporter outside the capture path through Week 8; consider automation
only after prospective evidence collection is complete and a separate review
approves it.
