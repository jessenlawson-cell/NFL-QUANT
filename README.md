# NFL QUANT
An NFL betting-research and discussion agent: find the strongest available bets, explain why the price matters, and stress-test bets you are considering or have placed.

Canonical workspace: C:\DEVELOPMENT\NFL QUANT.

## Start here
- AGENTS.md: repository behavior.
- DOMAIN_POLICY.md: current analytical rules and evidence standards.
- PROJECT_STATE.md: verified setup and outstanding limitations.
- docs/interface/NFL_QUANT_PROJECT_INSTRUCTIONS.md: matching ChatGPT Project instructions.
- docs/interface/WEEKLY_PROMPT.md: a reusable request, not a packet-upload gate.

Ask for a slate's top bets, compare markets/prices, or provide a bet to challenge. Use current research plus supplied evidence. Recommendations are price-conditional, not guarantees; no stakes or bet placement.

## Evidence and historical material
Data, source timestamps, losses, manifests, models, and old decisions remain preserved. Dataset descriptions explain their contents, not current eligibility. docs/historical/ contains superseded guidance; older specifications and plans are historical unless explicitly selected for review. Do not run old training, prediction, settlement, or scheduler-install commands as this agent's default workflow.

The existing Python package and dependency pins remain to preserve legacy reproducibility. The conversational agent uses available research/data tools and needs no new install or paid API. This does not claim the legacy runtime or every optional connector is currently healthy.

ChatGPT uploads are static copies, not automatic repository synchronization. Use the canonical instruction file and current evidence; ask Codex for repository work. Never expose credentials or upload provider data without appropriate rights.
