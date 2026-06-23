# Third-Party Relationship Graphs for Personal Context

Use this reference when extending a personal-context graph beyond `user ↔ person` edges to also include relationships among other people/entities.

## Core rule

An edge is not a permission.

A third-party relationship edge may help with local routing, disambiguation, grouping, and review prioritization. It must not grant permission to disclose context from one person/entity to another, write durable memory, or take external action.

Default third-party edge privacy:

```yaml
privacy:
  may_use_for_routing: true
  may_use_for_disambiguation: true
  may_disclose_to_subjects: false
  may_write_memory: false
```

## Recommended files

Add these to the personal-context workspace:

```text
schema-design.md
validate_personal_context.py
build_candidate_relationship_edges.py
test_build_candidate_relationship_edges.py
candidate-relationship-edges.yaml
third-party-relationships-reviewed.yaml
candidate-relationship-edges-report.md
propose_third_party_edge_clusters.py
test_propose_third_party_edge_clusters.py
third-party-edge-cluster-proposals.yaml
third-party-edge-cluster-review.md
verification-plan-and-results.md
```

Keep all local personal-context files private (`600`) and scripts executable/private (`700`).

## Metadata-first candidate builder pattern

Build candidate third-party edges from metadata only:

- Gmail headers: `from`, `to`, `cc`
- Message IDs as evidence pointers
- Topic labels/classes
- Shared domains/org hints
- Calendar/contacts metadata only if already in approved source scope

Do not copy into candidate edge records:

- subject text
- snippets
- email bodies
- document text
- account/confirmation numbers
- full raw evidence

Safe output evidence shape:

```yaml
evidence_summary:
  source_types: [gmail_headers]
  cooccurrence_count: 24
  direct_pair_count: 24
  shared_domains: [example.org]
  message_ids_sample: [message-id-1, message-id-2]
  topics_seen: [home_projects]
```

## Classification rules

Allowed neutral edge types:

```text
same_organization_or_team
vendor_group
community_group
advisor_group
unknown_association
```

Use `unknown_association` for sensitive or ambiguous co-occurrence. Never infer sensitive relationship labels from metadata alone.

Sensitive labels that require explicit user confirmation before approval:

- family/household relationship between third parties
- romantic relationship
- conflict/dispute
- legal relationship
- health/medical relationship
- financial/tax relationship
- hierarchy/manager/approval-chain claims

## Suppression and filtering

Suppress or downweight:

- Jim/self aliases
- generic domains (`gmail.com`, `outlook.com`, `icloud.com`, etc.)
- no-reply/newsletter/receipt/notification senders
- singletons without repeated co-occurrence
- cross-domain pairs from a single email unless explicitly supported by approved context

## Validator requirements

The personal-context validator should reject:

- approved third-party edges without explicit review provenance
- approved third-party edges with inferred-only confidence
- any third-party edge that grants disclosure by default
- any third-party edge that grants memory write by default
- sensitive relationship labels inferred from metadata
- raw snippets/body/document text in reviewed files
- sensitive defaults set to `allow`
- invalid enum values or non-UTC timestamps

## Test matrix

Before using the builder output, run tests that prove:

1. Neutral shared-domain co-occurrence can produce a local-only candidate edge.
2. Sensitive topics produce `unknown_association`, not tax/health/legal/family claims.
3. Jim/self aliases are skipped.
4. Generic domains are suppressed.
5. Subject/snippet/body text is omitted.
6. `may_disclose_to_subjects` remains false.
7. `may_write_memory` remains false.
8. Validator passes after generation.

## Cluster proposal layer

After generating `candidate-relationship-edges.yaml`, add a second local-only proposal step before any reviewed-file promotion.

Recommended outputs:

```text
third-party-edge-cluster-proposals.yaml
third-party-edge-cluster-review.md
```

Behavior:

- Group candidate edges by domain/team/context so the user reviews clusters, not hundreds of individual edges.
- Split output into:
  - `proposed_clusters`: safe neutral clusters that can be reviewed for local routing/disambiguation.
  - `sensitive_review_only_clusters`: tax/health/legal/finance/family-sensitive clusters that must not be promoted from metadata alone.
- Set every proposed cluster to `proposed_review_status: pending_review`, never `approved`.
- Keep `may_disclose_to_subjects: false` and `may_write_memory: false` in every proposal.
- Omit raw subjects, snippets, bodies, notes from candidate edges, and document text from proposal output.
- Create a concise Markdown review prompt with cluster name, domain, proposed neutral type, scope, people/edges/cooccurrences, and default privacy.

Labeling pitfalls:

- Do not let noisy topic labels override strong domain context too broadly. Example: a known church domain can normalize to `community_group` / `church_nonprofit`, but a vendor domain that merely co-occurs with a `church_nonprofit` topic should not become a church/community team.
- Treat tax/finance/health/legal co-occurrence as `sensitive_review_only`, even if counts are high.
- High co-occurrence count is a review-priority signal, not proof of relationship type.

Additional cluster-proposal tests should prove:

1. Safe normal-domain clusters are proposed as `pending_review`, not approved.
2. Sensitive clusters are separated into manual-review-only output and not proposed for promotion.
3. Proposal output contains no raw source text and no permission escalation.
4. Domain-specific label overrides are narrowly scoped and tested to avoid broad false positives.

## Review workflow

Review by cluster/domain, not one edge at a time.

Promotion rules:

1. Promote only safe neutral clusters by default.
2. Keep third-party edges local-only unless the user separately approves disclosure or memory use.
3. Record field-level provenance and user approval timestamp.
4. Never promote sensitive third-party edges based on metadata alone.
5. Do not create durable Hermes memory from candidate edges without an exact memory diff and explicit approval.

## Example candidate edge

```yaml
edge_id: edge_paula_wallin_stephanie_eustis_cpa_team
subject_person_id: person_paula_wallin
object_person_id: person_stephanie_eustis
relationship_edge_type: advisor_group
context_scope: cpa_tax_advisory
direction: undirected
sensitivity: tax
confidence: inferred_medium
review_status: candidate
evidence_summary:
  source_types: [gmail_headers]
  cooccurrence_count: 8
  shared_domains: [wallin-cpa.com]
  message_ids_sample: [msg1, msg2]
privacy:
  may_use_for_routing: true
  may_use_for_disambiguation: true
  may_disclose_to_subjects: false
  may_write_memory: false
notes: Metadata-only candidate edge. Does not grant disclosure or memory permission.
```

## Senior-engineer pitfall

A rich relationship graph increases usefulness and privacy risk at the same time. Keep three layers separate:

1. candidate graph: inferred/local-only
2. reviewed graph: user-approved but still not disclosure permission
3. durable memory: compact exact entries only after separate approval
