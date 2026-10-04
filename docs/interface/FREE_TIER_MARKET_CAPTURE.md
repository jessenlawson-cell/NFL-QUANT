# Weekly market intelligence: free-tier operation

Routine maximum: 84 credits per Tuesday–Monday week. Preserve 80 provider credits;
on a 500-credit plan this limits routine use to 420 per actual billing cycle.
The current balance is read from free event-discovery headers, not guessed from dates.
External calls on the same API key consume this same allowance. Reserve use is not automatic.

## Captures (America/Toronto)
- Main board: Wednesday 18:00, Friday 18:00, Sunday 12:00, Monday 18:00. Each costs at most 3.
- Core props: once per game, 45–90 minutes before kickoff; four markets, maximum 16 games.
- Deeper props: eight additional markets bundled into that game's core request. Defaults to
  the earliest eligible game; `--deep-event EXACT_PROVIDER_EVENT_ID` selects a different one.
- Eight selected reference books are candidates, not fixed sharp anchors. No bet365 Ontario
  coverage. US/Canadian book prices are not interchangeable or guaranteed executable.
- A 15-minute local task discovers schedules for zero credits and captures only due slots.
  Outside windows, no charged call. No catch-up after kickoff; no uncertain-call retries.

Core: passing yards, rushing yards, receiving yards, receptions.
Extra: passing TDs, attempts, completions, interceptions; rush attempts, longest rush;
longest reception and anytime TD. Markets/books may be absent; missingness is reported.

## Run and inspect
`py -3.14 scripts/capture_market_intelligence.py` is offline/no-network dry-run.
`py -3.14 scripts/capture_market_intelligence.py --preflight` performs zero-credit
live event discovery and checks actual account quota without requesting any odds.
`powershell -NoProfile -File scripts/install_market_capture_task.ps1 -DryRun` checks setup.
Installer without `-DryRun` registers `NFL-QUANT-Free-Market-Capture`; it never immediately runs.
Worker `--execute` authorizes budgeted live calls. Reads THE_ODDS_API_KEY from environment
or local .env without logging it. No Docker or Codex reasoning session is required.

Keep Windows powered on, awake, connected to internet and your user signed in (locked is OK).
Wake timers are requested, not guaranteed by firmware/power policy. Shutdown or a closed lid
can miss windows. For each game, inspect actual capture coverage rather than assuming success.

Local ledger: data/runtime/market_intelligence/captures.sqlite3.
Raw immutable envelopes: data/raw/market_intelligence/<week>/.
Packets and cumulative immutable weekly handoffs: outputs/nfl-quant-interface/<week>/.
Log: logs/market-intelligence.log. These data outputs are ignored by Git.
Read task state/last result in Windows Task Scheduler. A nonzero result requires review.

Upload the newest `weekly_handoff_*.json` to the weekly ChatGPT chat. Its generation time
does not make older quotes current. Retain snapshot/quote timestamps, coverage gaps and
limitations. ChatGPT is not auto-connected to local files. Provide actual bet365 Ontario
quotes separately; current injuries, weather and player usage need separate sources.

## Safety and reconciliation
An OS file lock serializes discovery through completion, preventing stale quota overwrites.
SQLite reservations serialize charged calls across processes. Duplicate slots are skipped;
an incomplete/failed call blocks every other charged call until an operator verifies the
provider balance and raw files. Never delete a reservation to blindly retry it.
Weekly observed event inventories retain missed games after they disappear from discovery;
updated handoffs report missed windows and unresolved calls even when no capture succeeds.
Raw responses are saved before parsing. GSIS player IDs remain null; provider descriptions
are display-only, never name joins into football data. No model training/scoring, stakes,
EV or joint parlay probabilities are computed. No historical database/spec changes.

420 credits can support five 84-credit weeks, but a billing-cycle boundary can intersect
six partial football weeks. Actual balance protection takes precedence; optional depth and
board coverage can be skipped. Coverage, uninterrupted power and external key usage remain
limits: the free plan cannot guarantee every market every week or real-time steam tracking.

Sources verified 2026-10-04: https://the-odds-api.com/liveapi/guides/v4/;
https://the-odds-api.com/sports-odds-data/betting-markets.html;
https://the-odds-api.com/sports-odds-data/bookmaker-apis.html.
