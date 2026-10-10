# Free-tier market capture implementation plan

Goal: weekly market intelligence without historical scoring or exhausting the free allowance.
Spec: approved chat plan: four board captures (12), four props per game (64 maximum),
eight extra markets for one game (8); 84/week, 420 routine credits/cycle, 80 protected.
Architecture: one stdlib Python worker, its own SQLite ledger/raw files/ChatGPT packets,
and one Windows task. No new dependencies or legacy model/database changes.

## Tasks and verification
- [x] Test-first worker: budget exhaustion, reservation concurrency, ambiguous-call blocking,
  duplicate slots, quota reset, kickoff windows, identity preservation, secret-safe errors.
- [x] Implement free events discovery, batched board/event calls, raw-first immutable capture,
  exact provider event IDs, unresolved GSIS IDs, coverage reporting and packet export.
- [x] Add 15-minute Windows scheduler installer with no immediate paid run; dry-run verify.
- [x] Run focused checks then repository suite, independent review, record actual activation.

Review focus: first-cycle external usage; DST; missed laptop windows; absent prop coverage;
no bet365 Ontario feed; missing quota headers; failure after a billed response.

Ruling: work in existing feature checkout, touching only new files and PROJECT_STATE;
preserve the pre-existing market_odds.csv change. No commit/push or dependency installation.
Ruling: 80 credits remain protected until explicit reserve-use approval. This is a budgeted
capture service, not a guarantee that all books/markets will be returned or alpha established.

Review fixes: OS lock covers free discovery through paid completion; both cycle and weekly
headroom prioritize core props; persistent inventory and change-triggered handoffs expose
missed/failed captures. Regression tests watched fail, then pass.
Declined-to-judge rulings: free discovery returned x-requests-last=0 and remaining=498 live;
actual reset transitions are header-tested, not a live billing reset; book/prop coverage and
hardware wake behavior remain unguaranteed. Windows timezone resolution was checked live.

User-expanded scope: align all ACTIVE policies/docs/tests with market intelligence;
preserve hashed historical specs but mark them non-operative via LEGACY_ARCHIVE.md.
Completed: AGENTS, DOMAIN_POLICY, README, PROJECT_STATE, ChatGPT instructions/weekly prompt.
Instruction length 5,258. Full suite green with two Linux PowerShell-only skips after removing
obsolete PASS-only text assertions. Fourteen worker tests green; targeted lint green.
Task registered and verified Ready/PT15M; all 19 historical tasks remain Disabled.
No remote ChatGPT Project edit, commit or push. No paid verification calls.
