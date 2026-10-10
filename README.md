# NFL QUANT
NFL market intelligence and betting stress tests: current odds, market-specific reference comparisons, observed movements, football evidence and explicit uncertainty. Target: bet365 Ontario. Not a predictive-model experiment or automated betting system.

Canonical workspace: C:\DEVELOPMENT\NFL QUANT.

## Start here
- AGENTS.md: repository behavior.
- DOMAIN_POLICY.md: current analytical rules and evidence standards.
- PROJECT_STATE.md: verified setup and outstanding limitations.
- docs/interface/NFL_QUANT_PROJECT_INSTRUCTIONS.md: matching ChatGPT Project instructions.
- docs/interface/WEEKLY_PROMPT.md: a reusable request, not a packet-upload gate.
- docs/interface/FREE_TIER_MARKET_CAPTURE.md: active free-tier capture workflow and limits.
- LEGACY_ARCHIVE.md: preserved material that cannot govern the new interface.

Ask for a slate's top bets, compare markets/prices, or provide a bet to challenge. Use current research plus supplied evidence. Recommendations are price-conditional, not guarantees; no stakes or bet placement.

## Evidence and historical material
Data, source timestamps, losses, manifests, models, and old decisions remain preserved. Dataset descriptions explain their contents, not current eligibility. docs/historical/ contains superseded guidance; older specifications and plans are historical unless explicitly selected for review. Do not run old training, prediction, settlement, or scheduler-install commands as this agent's default workflow.

The existing Python package and dependency pins remain historical. Active capture is
`py -3.14 scripts/capture_market_intelligence.py --execute`; offline dry-run omits `--execute`.
It never imports model/scoring code or writes the historical database. Routine ceiling:
84 credits/week, preserving 80 provider credits per 500-credit billing cycle. No new dependencies.
Read the capture guide for the verified scheduler state and power/sign-in requirements.

The Odds API does not list bet365 Ontario. Obtain separately verified target quotes; do not
substitute US prices. No-vig and cross-book discrepancies do not prove independent positive EV.
Sparse snapshots cannot establish real-time steam or defensible correlated-parlay probabilities.

ChatGPT uploads are static copies, not automatic repository synchronization. Use the canonical instruction file and current evidence; ask Codex for repository work. Never expose credentials or upload provider data without appropriate rights.
