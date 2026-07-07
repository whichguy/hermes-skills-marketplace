# Privacy-first personal context / relationship graph planning

Use this reference when planning systems that infer personal context from Gmail, calendar, contacts, files, chat, or other private records.

## Core architecture

Separate these layers so discovery never silently becomes truth:

1. Raw discovery cache: local/private, metadata-only by default, short retention.
2. Candidate graph: inferred people/orgs/domains/edges with confidence and review status.
3. Reviewed canonical context: user-approved stable IDs, aliases, relationships, circles, and policies.
4. Durable memory: tiny approved facts only, never raw evidence or sensitive details.
5. Runtime resolver: fail-closed policy lookup that returns only an allowed-context packet.

## Third-party relationship edges

Model relationships between other people/entities, not only relationships to the user, but treat them more strictly.

Good uses:
- routing and disambiguation
- grouping teams/advisors/vendors/households
- review prioritization
- local context selection

Default edge privacy:

```yaml
may_use_for_routing: true
may_use_for_disambiguation: true
may_disclose_to_subjects: false
may_write_memory: false
```

Key invariant:

```text
An edge is not a permission.
```

A candidate edge like "Paula Wallin and Stephanie Eustis appear to be the same CPA team" can help local tax routing, but it does not authorize disclosing tax/private context between them or writing the edge to durable memory.

## Metadata-first discovery

Default to metadata-only. Treat all of these as potentially sensitive metadata:

- email subjects
- snippets
- calendar titles/locations/descriptions
- Drive filenames
- contact notes
- attendee lists

Body/snippet/document reads require explicit bounded approval per source/run.

## Canonical schema pattern

Prefer stable IDs and enum-controlled YAML/JSON-compatible records:

- `people.yaml`
- `organizations.yaml`
- `relationships-reviewed.yaml` for relationships involving the user
- `third-party-relationships-reviewed.yaml` for approved other-person edges
- `candidate-relationship-edges.yaml` for inferred local-only edges
- `circles.yaml`
- `context-sharing-policy.yaml`
- `people-engagement-policy.yaml`
- `policy-decisions-log.jsonl`

Use per-field provenance for policy-bearing facts. Do not let an entire reviewed record make every alias/relationship user-confirmed.

## Validator requirements

Before runtime use, add a fail-closed validator that rejects:

- approved records with inferred confidence
- raw snippets/body/document text in reviewed files
- sensitive defaults set to `allow` without exact approval
- duplicate approved email aliases unless marked shared/ambiguous
- third-party edges that grant disclosure or memory by default
- sensitive/romantic/conflict/family/legal/health/financial third-party labels inferred from metadata alone
- non-UTC timestamps
- enum drift

If validation fails, runtime should use global deny/minimal context.

## Audit and retention

Every discovery run should have a run manifest with `run_id`, record counts, output files, partial-run/errors, and `retention_expires_at`.

Audit policy/memory/approved-edge changes without raw sensitive content. Useful fields:

- event_id
- timestamp
- actor/tool
- approval source ref
- changed files
- before/after hashes
- sensitivity
- memory_written
- external_side_effect

## Durable memory boundary

Never write memory automatically from candidate graph data. Only exact user-approved compact stable facts belong in memory. Avoid raw evidence, amounts, identifiers, health/legal/tax details, and speculative relationships.
