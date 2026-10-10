# bet365 Ontario target-feed review

Reviewed: 2026-10-04. Status: public-documentation review completed; Ontario feed not validated.

## Decision

Keep the existing budgeted The Odds API capture routine unchanged. Continue using separately supplied, timestamped bet365 Ontario quotes for target-book comparisons. Do not install a scraper/MCP server, purchase a subscription, or substitute generic bet365 prices for Ontario prices based on this review.

The constraint is verified regional data access and permitted use, not a lack of Python ingestion code. No authenticated sample request, provider support message, installation, subscription, or provider-credit expenditure was performed for this review.

## Verified findings

- [The Odds API bookmaker catalog](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html) does not list bet365 Ontario. Its listed bet365_au feed is not an Ontario NFL substitute. A bookmaker parameter or LLM tool cannot create unsupported coverage.
- [Odds-API.io's catalog](https://odds-api.io/sportsbooks) lists generic Bet365 and bet365 NJ; the reviewed public catalog does not establish Ontario-specific coverage. Absence of confirmation is not proof coverage is impossible.
- [Current Odds-API.io pricing](https://odds-api.io/pricing) states new free keys are paused indefinitely. Existing free keys retain two recreational bookmakers, 100 requests/hour and 500/day; sharp/exchange books require a paid plan. Older free-signup examples are not reliable evidence of current access. The listed entry subscription is GBP 49/month, with checkout conversion; no purchase is approved.
- [Odds-API.io terms, section 9](https://odds-api.io/terms) require prior written consent for third-party redistribution/sublicensing. Confirm whether the intended private ChatGPT upload/processing and retained snapshots are permitted; permission for another provider does not establish this provider's permission.
- An [official Python SDK](https://github.com/odds-api-io/odds-api-python) and [official MCP server](https://github.com/odds-api-io/odds-api-mcp-server) exist. Their availability does not verify Ontario coverage, data rights, or connection to this ChatGPT Project. README review is not a source/dependency security audit. The MCP includes bookmaker-selection mutations and arbitrage/stake outputs; do not expose it unrestricted to the interface.

## Provider questions before implementation

1. Does your feed explicitly represent bet365 Ontario, rather than UK/international/NJ/Australia? Supply the exact bookmaker key, jurisdiction, and representative NFL responses.
2. Which NFL moneyline, spread, total and player-prop contracts are covered? Provide exact lines, selections, settlement rules, source quote timestamps, update cadence and known delays.
3. Does the license permit automated personal research, local immutable caching and private ChatGPT Project uploads/processing/retention? Please confirm in writing.
4. What currently available plan provides that coverage, and what are its charges, request limits and overage controls? Is an existing free key eligible, if applicable?

## Acceptance checks

After access, rights and any spending are approved, compare contemporaneous provider samples against independently observed Ontario quotes across multiple games, market types and observation times. Match jurisdiction, event, market, selection, line, price and settlement semantics. Record discrepancies, missing markets, timestamps and latency; do not claim executable/account-specific availability from an aggregate feed alone.

Reject regional ambiguity, missing quote times, contract mismatches or stale samples. Preserve raw responses and provenance. Player descriptions remain display-only; football-data joins require resolved GSIS IDs, never names.

## Minimal future integration

If the feed passes those checks, add a narrow adapter to the existing standalone capture worker with explicit quotas, immutable snapshots and failure controls. Initially export target quotes in the existing weekly handoff. Only add an LLM connector if static handoffs become a demonstrated bottleneck: expose read-only cached quotes and coverage, not unrestricted live calls, provider account mutations, stakes or execution. Keep dynamic market-specific references separate from the target quote; discrepancies are not automatically positive EV.

This review does not change active policies, schedules, credit ceilings, models, runtime databases or historical evidence. All coverage and commercial claims must be rechecked before purchase or integration.
