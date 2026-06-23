# Personal Context Graph Verification and Hermes Integration Pattern

Use this reference when a session generates a personal operating profile, relationship/context graph, or ambient automation plan from Gmail/Calendar/Drive/Contacts.

## What worked in the session

- Build local review artifacts first, not memory entries:
  - `profile-draft.md`
  - `relationships.yaml`
  - `domains.yaml`
  - `review-queue.md` / cleaned review checklist
  - `context-verification-analysis.md`
  - `hermes-integration-plan.md`
- Keep discovery read-only and metadata-first:
  - Gmail metadata/snippets before full bodies.
  - Calendar metadata only.
  - Drive metadata only unless user explicitly requests content reads.
  - Contacts names/emails/orgs; avoid phone numbers unless needed.
- Treat generated relationship roles as candidates, not facts.
- Use a second verification pass to identify noisy labels before asking the user to approve memory writes.

## Common classifier failure modes

- **CC-heavy false importance:** A person can score high from repeated CCs while having little direct relationship signal. Track direct signals separately from CC counts and do not promote CC-heavy nodes without review.
- **Generic keyword pollution:** Words like `payment`, `receipt`, `project`, `home`, `meeting`, or `travel` can cause vendors to look like personal relationships.
- **Generic domain noise:** Domains such as `gmail.com`, `google.com`, and broad no-reply domains are usually not useful organization nodes.
- **Vendor-as-person mistakes:** Retail, subscription, health/fitness, travel, tax, or utility senders should usually be routing/alert sources, not relationship nodes.
- **Sensitive domain handling:** Health/medical/fitness senders should default to sensitive/review-first; do not persist them unless the user explicitly approves.

## Useful verification checks

- Count people/org/domain/rule nodes after generation.
- Print top people with role, contexts, total evidence, and direct-vs-CC evidence.
- Flag nodes where `cc_count / total_signal_count >= 0.7` as review-required.
- Flag vendor/business domains with personal roles such as family, church, tax, or travel when the domain suggests a vendor/source.
- Exclude or down-rank generic domains from organization output.
- Add domain overrides for known authorities/vendors only as routing hints, not final truth.

## Recommended Hermes integration model

Use three layers:

1. **Durable memory** — only compact, reviewed, stable facts:
   - Self aliases.
   - Confirmed close family/household roles.
   - Confirmed important organizations/domains.
   - User workflow/preferences.
   - Never raw tax amounts, health details, account identifiers, email snippets, or unreviewed inferences.

2. **Local private context files** — richer graph/evidence under a user-owned directory such as `/opt/data/personal-context/`:
   - Suitable for private working context that Hermes can inspect on demand.
   - Keep raw audit/detail files out of chat unless explicitly requested.

3. **Ambient cron jobs** — narrow watchers with quiet defaults:
   - Tax/CPA watcher: Inbox-only, known tax authorities/CPA domains, alert on actionable payment/deadline/duplicate/document-request events.
   - Morning/admin brief: concise action list, not a private data dump.
   - Travel watcher: approved travel sources + calendar conflicts/missing pieces/changes.
   - VIP unanswered watcher: only approved contacts; draft replies only.

## Review checklist shape

Prefer a cleaned user review file grouped by actionability:

- Tier 1: likely safe/useful after confirmation.
- Tier 2: useful as vendor/routing sources, not personal relationships.
- Tier 3: ignore or sensitive by default.
- Ambient automation approvals.
- Explicit memory approval rule.

Ask the user to mark: Save / Correct / Ignore / Sensitive. Do not infer approval from the generated graph itself.
