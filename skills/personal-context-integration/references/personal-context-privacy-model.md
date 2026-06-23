# Personal Context Privacy Model

This reference captures the durable workflow learned from building a Hermes personal operating profile and relationship graph from Google Workspace metadata.

## Problem class

The user wants Hermes to become more ambient and useful by understanding personal domains, relationships, vendors, responsibilities, and recurring admin/tax/travel/home/church/work context.

The risk is that metadata/snippet inference can produce wrong or sensitive durable facts. Durable memory and cron jobs amplify those mistakes across future sessions.

## Correct architecture

Use a strict bridge model:

```text
Raw sources → candidate local graph → review queue → approved-context.yaml → proposed memory diff / cron prompts
```

Only `approved-context.yaml` should feed durable memory or ambient cron jobs.

## Session-proven files

A good local workspace contained:

- `profile-graph-plan.md`
- `build_profile_graph.py`
- `profile-draft.md`
- `relationships.yaml`
- `domains.yaml`
- `ambient-alert-rules-draft.yaml`
- `review-queue-clean.md`
- `context-verification-analysis.md`
- `hermes-integration-plan.md`
- `policy.yaml`
- `approved-context.yaml`
- `tier1-review-prompt.md`
- `STATUS.md`

## Recommended `policy.yaml` sections

- `sensitive_categories`
- `generic_org_domains`
- `automated_sender_patterns`
- `memory_policy.allowed_after_approval`
- `memory_policy.denied`
- `telegram_redaction`
- `cron_policy`
- `domain_overrides`

## Recommended `approved-context.yaml` sections

- `metadata`
- `approved_self_aliases`
- `approved_people`
- `approved_organizations`
- `approved_alert_sources`
- `muted_senders_or_domains`
- `sensitive_do_not_store`
- `memory_entries_written`

## Common false positives

- CC-heavy threads inflate relationship importance.
- No-reply vendors look like people.
- Generic domains like Gmail/Google are not useful org nodes.
- Product returns and receipts can pollute tax/finance topics.
- Health/fitness senders may be sensitive even if only vendor-like.
- Tax authorities should be alert-routing sources, not memory details.

## Tier 1 review pattern

Start with only high-value, low-risk review items:

1. Self aliases.
2. Close family/household labels.
3. CPA/tax context as alert routing, no details.
4. Church/nonprofit broad org context.
5. Sensitive defaults: health/medical off, tax details off, no important-contact watcher yet.

Ask for labels/corrections, then generate an exact memory diff before saving.

## Safe cron rollout

Inventory existing cron jobs first. Prefer updating/refining existing jobs over adding duplicates.

Order:

1. Morning brief refinement.
2. Travel/calendar alert refinement.
3. Narrow tax/CPA watcher.
4. Important-contact watcher last.

Cron prompts should be read-only, quiet by default, and should never write memory or mutate external state.

## Telegram summary style

For this user, use concise Telegram-native formatting:

- Short headings.
- Bullets, not tables.
- Clear status and next step.
- Avoid dumping raw graph/audit content.
