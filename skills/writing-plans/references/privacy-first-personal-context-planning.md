# Privacy-First Personal Context Planning Reference

Use this reference when writing or reviewing implementation plans for personal context, relationship graphs, memory systems, email/calendar/contact discovery, or agent engagement policies.

## Senior-engineer review checklist

Before implementation, ensure the plan explicitly covers:

1. **Discovery is not truth**
   - Raw discovery and candidate graphs stay local/private.
   - User approval or correction is the only path to canonical truth.
   - Inferred facts never become durable memory without an exact approved diff.

2. **Metadata-only by default**
   - Snippets, body text, attachments, document contents, contact notes, and raw source text require explicit bounded approval.
   - Treat email subjects, calendar summaries/locations, Drive filenames, and contact notes as potentially sensitive metadata.

3. **Canonical schemas and enums**
   - Define one schema authority before generating reviewed files.
   - Normalize enum names across docs and files for context classes, permission modes, sensitivity, review status, confidence, action autonomy, and channels.

4. **Machine validation before runtime use**
   - Add a validator before policy/runtime integration.
   - Fail if reviewed records lack stable IDs, review metadata, provenance, approved status with user-confirmed confidence, valid enums, or ISO-8601 UTC timestamps.
   - Fail if reviewed files contain raw snippets/body text, account numbers, confirmation numbers, credentials, or sensitive defaults set to allow without approval.

5. **Per-field provenance**
   - Do not let a whole record inherit one trust level.
   - Track provenance separately for display names, aliases, circle membership, relationship labels, and policy-bearing fields.

6. **Fail-closed runtime policy**
   - Ambiguous identity: do not use person-specific context.
   - Unknown person + sensitive/unknown topic: ask or deny.
   - Uncertain topic with sensitive signals: ask or deny.
   - Policy validation failure: global deny/minimal context.
   - Draft generators receive only an allowed-context packet, never the full graph/policy record.

7. **Permission merge semantics**
   - Define strictness ordering explicitly, e.g. `deny > local_only > ask_each_time > alert_only > summarize_only > allow`.
   - Topic safety rules outrank person/org/circle defaults.
   - Overrides may restrict but must not weaken a global/topic safety deny without explicit approval.

8. **Retention and deletion**
   - Raw/candidate artifacts need `retention_expires_at`.
   - Reviewed canonical records must not depend on raw evidence remaining forever.
   - Cleanup/deletion should be auditable and safe.

9. **Auditability**
   - Audit entries should include event ID, run ID, actor, approval source, changed files, before/after hashes, sensitivity, memory diff ID, and external side-effect flag.
   - Audit logs should avoid raw sensitive content.

10. **Implementation gates**
   - No durable memory writes without exact approved diff.
   - No cron/runtime automation until schemas, validator, and policy resolver tests pass.
   - No candidate-to-approved promotion without review/provenance.

## Minimal test matrix

Plans should require tests for:

- CPA/tax email with amount → alert only/minimal actionable; no memory; no raw snippet.
- Health provider domain → deny/store nothing unless explicitly enabled.
- Work/org operational email → permitted business context; family/tax/health denied.
- Community/church contact plus family detail → deny or ask_each_time.
- Ambiguous name with multiple candidates → ask/ambiguous; no person-specific context.
- No-reply vendor with receipt/order number → suppress or minimal summary; no identifiers.
- Calendar private location → do not expose unless policy allows logistical/travel context.
- Drive filename with tax/legal/health keyword → sensitive metadata; do not download content.
- Policy validation failure → global deny/minimal context.

## Recommended plan shape

For personal-context systems, plans should produce artifacts in this order:

1. Schema design and canonical enums.
2. Validator.
3. Bootstrap approval migration into stable ID-based canonical records.
4. Circle/global policies.
5. Runtime resolver and tests.
6. Exact memory diff for approval.
7. Optional automation only after all gates pass.
