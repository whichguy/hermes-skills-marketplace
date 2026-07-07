# Privacy-sensitive relationship graph planning

Use this reference when writing plans for personal-context systems, relationship graphs, memory systems, inbox/contact/calendar mining, or any feature that infers facts about people.

## Core design rule

A graph edge is not a sharing permission.

Relationship edges may help local routing, disambiguation, prioritization, and explanation, but they do not grant permission to disclose context from one person/entity to another.

## Required layers

1. Raw discovery cache
   - Local/private only.
   - Metadata-only by default.
   - Snippets/body/document text require explicit bounded approval.
   - Retention metadata required.

2. Candidate graph
   - Inferred people, organizations, domains, and relationship edges.
   - Confidence + provenance required.
   - Not used directly for durable memory or outgoing messages.

3. Reviewed canonical context
   - User-approved identities, relationships, circles, policies.
   - Stable IDs for people/orgs/edges.
   - No raw snippets or sensitive details.

4. Runtime policy resolver
   - Fail closed on ambiguity, validation failure, or sensitive unknowns.
   - Drafting receives only an allowed-context packet, not full records.

5. Durable memory
   - Compact stable approved facts only.
   - Never raw evidence, amounts, health/legal/tax details, account identifiers, or inferred relationships.

## Third-party relationship edges

Model relationships between other people/entities when useful, but keep them stricter than direct user relationships.

Candidate edge example fields:

```yaml
edge_id: edge_paula_wallin_stephanie_eustis_cpa_team
subject_person_id: person_paula_wallin
object_person_id: person_stephanie_eustis
relationship_type: same_organization_or_team
context_scope: cpa_tax_advisory
confidence: inferred_medium
review_status: pending_review
privacy:
  may_use_for_routing: true
  may_disclose_to_subjects: false
  may_write_memory: false
```

Rules:

- Prefer weak labels like `same_organization_or_team`, `advisor_group`, `vendor_group`, or `unknown_association` unless the user confirms a personal relationship.
- Do not infer intimate, romantic, conflict, health, legal, tax, financial, or family details from co-occurrence alone.
- Approved third-party edges require explicit review provenance.
- Disclosure permission remains separate from routing permission.

## Planning checklist

Plans for this class of system should include:

- Canonical enum/schema definition before implementation.
- Machine validator before runtime use.
- Per-field provenance, not just record-level source.
- Retention/deletion process for raw and candidate artifacts.
- Audit log with event IDs, actor, approval source, changed files, hashes, and external side-effect flag.
- Explicit fail-closed runtime rules.
- Test matrix for sensitive cases: tax amount, health provider, ambiguous identity, no-reply receipt identifiers, private calendar location, sensitive Drive filename, policy validation failure, and third-party edge non-disclosure.
