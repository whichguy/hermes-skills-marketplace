# Advisor Consensus: Skills Review (2026-07-05)

3-seat panel (DeepSeek V4 Pro, Kimi K2.7 Code, Minimax M3) reviewed two new skills
and the devloop fixes from the 2026-07-05 session.

## Area 1: cron-assumption-verification

### Consensus: 4 action items (all 3 agreed)

1. **Severity tiers (fail-open/fail-closed):** Advisory operations fail-open with
   warning; mutating operations fail-closed with alert. Applied as "Fail-Open vs
   Fail-Closed" section.

2. **Multi-source conflict resolution:** API > email for real-time status; email >
   API for booking details; surface both on conflict; fetch most recent source.
   Applied as "Multi-Source Conflict Resolution" section.

3. **Missing meta-review dimensions:** Cost drift, permission scope creep, user
   model drift, cascading failure surface. Applied as 4 new rows in the
   Meta-Review Dimensions table.

4. **State schema versioning:** Added `schema_version`, `acknowledged_at`,
   `silenced_until`, `source_health_log` to the state storage example. Added
   pitfall #11 for alert storms.

### Split decisions (2/3 agreed)

- **Split review cadence by volatility** (Kimi + Minimax): daily for flights,
  weekly for slow-drift. Noted but not applied — the meta-review is already
  weekly and the verification gate handles per-run checks.

## Area 2: calendar-event-planning

### Consensus: 3 action items (all 3 agreed)

1. **Enrich existing event workflow:** GET→verify→merge→PATCH for airline
   auto-invites, meeting invites, conference imports. Applied as "Enriching
   Events Created by Other Systems" section.

2. **Source authority hierarchy:** "Calendar is authoritative" means it's the
   display layer, not the data layer. Most recent verified primary source wins.
   Applied as "Source Authority Hierarchy" section.

3. **Timezone rules:** Every event in its local timezone, not Jim's home.
   Applied as "Time Zone Rules" section.

### Split decisions (2/3 agreed)

- **Attendee privacy caveat** (Kimi + Minimax): Solo business trips should ASK
  before adding Kelly, not auto-recommend. Applied as privacy considerations
  note in the Attendee Advice section.

### Noted (1/3)

- **Replace expiring deep links** (Minimax): Use airline home + confirmation
  code instead of Gmail deep links that expire. Noted but not applied — Gmail
  deep links are the current standard and haven't been observed to expire.

- **Cancellation cascade** (Kimi): Flight cancelled → mark entire chain. Noted
  but not applied — this is a separate workflow, not a calendar-event-planning
  concern.

## Area 3: Devloop Fixes

### Consensus: YES — the 3-layer defense is architecturally correct

All 3 advisors confirmed the 3-layer defense (prompt prevention → static lint
gate → judge rejection) is the right architecture. Three concrete issues found
and fixed:

1. **Integration test example was tautological** (Kimi + Minimax):
   `returncode in (0,1)` → `returncode == 0` with real assertion.

2. **External-system trigger too broad** (all 3): Narrowed to "INITIATES
   outbound call" vs "CONSUMES output."

3. **Missing impl-phase defense** (Minimax): Added EXTERNAL BOUNDARY RULE to
   coder prompt — must call real binary directly, not wrap in mockable helper.

## Cross-Area Finding (Minimax)

All 3 areas share the same fail-open vs fail-closed decision made ad-hoc per
skill. Should be a shared principle: advisory operations fail-open, mutating
operations fail-closed. Applied to cron-assumption-verification; noted for
future skill design.
