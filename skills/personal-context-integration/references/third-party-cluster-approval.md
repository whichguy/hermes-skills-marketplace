# Third-Party Cluster Approval Pattern

Use this reference when a user approves a review package generated from `third-party-edge-cluster-proposals.yaml`.

## Approval scope

A bare approval after the user saw the cluster review summary means:

- Promote safe neutral clusters to `third-party-relationships-reviewed.yaml`.
- Treat broad wording such as “approve all of these” as applying to the safe neutral proposal list only; it does not override manual-review-only/sensitive section labels.
- Use the approved clusters only for local routing and disambiguation.
- Keep disclosure and memory-write permissions false.
- Keep sensitive/manual-review-only clusters unpromoted, but preserve a compact `sensitive_review_only_clusters_not_promoted` record when useful for future suppression/review.
- Do not write Hermes memory or modify cron jobs.

This mirrors the broader personal-context gate pattern: local reviewed files first, exact memory diff later, cron only after separate explicit approval.

Implementation note: build the reviewed file idempotently from `third-party-edge-cluster-proposals.yaml` so repeated approvals or regenerated proposals produce stable reviewed records with fresh review metadata. Verification should fail closed if regression tests are missing; restore/recreate the tests before claiming that the approval path is verified.

## Reviewed record shape

For each safe cluster, write a reviewed third-party record with fields like:

```json
{
  "relationship_id": "approved_cluster_example_com_home_projects",
  "source_cluster_id": "cluster_example_com_home_projects",
  "relationship_type": "vendor_group",
  "relationship_label": "example.com vendor/project team",
  "direction": "undirected",
  "domain": "example.com",
  "context_scope": "home_projects",
  "sensitivity": "normal",
  "confidence": "user_confirmed",
  "status": "approved",
  "approved_use": ["local_routing", "disambiguation"],
  "candidate_person_ids": [],
  "candidate_edge_ids": [],
  "evidence_summary": {
    "edge_count": 0,
    "person_count": 0,
    "total_cooccurrences": 0,
    "topics_seen": [],
    "source": "candidate-relationship-edges.yaml"
  },
  "privacy": {
    "may_use_for_routing": true,
    "may_use_for_disambiguation": true,
    "may_disclose_to_subjects": false,
    "may_write_memory": false
  },
  "review": {
    "status": "approved",
    "reviewed_by": "Jim",
    "reviewed_at": "YYYY-MM-DDTHH:MM:SSZ",
    "source": "Telegram approval after third-party-edge-cluster-review.md summary",
    "approval_scope": "neutral local routing/disambiguation only; no disclosure permission; no memory write permission"
  },
  "created_at": "YYYY-MM-DDTHH:MM:SSZ",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

## Sensitive clusters

Do not promote clusters whose proposal section is `sensitive_review_only_clusters`. Preserve a compact record under a section such as:

```json
"sensitive_review_only_clusters_not_promoted": [
  {
    "source_cluster_id": "sensitive_cluster_example_com_tax",
    "domain": "example.com",
    "sensitivity": "tax",
    "reason": "manual_review_only_do_not_promote_from_metadata",
    "candidate_edge_ids": [],
    "privacy": {
      "may_use_for_routing": true,
      "may_use_for_disambiguation": true,
      "may_disclose_to_subjects": false,
      "may_write_memory": false
    }
  }
]
```

## Verification checklist

After promotion, run the local validation/test suite appropriate to the repository and also assert:

- reviewed third-party relationships count matches the approved safe clusters;
- every approved record has `status: approved` and `confidence: user_confirmed`;
- every approved record has `may_disclose_to_subjects: false`;
- every approved record has `may_write_memory: false`;
- sensitive/manual-review-only clusters remain unpromoted;
- reviewed output contains no raw snippets, raw bodies, credentials, account numbers, or source text;
- `STATUS.md` names the current phase and remaining approval gates;
- `audit-log.jsonl` records the user approval source, changed files, and verification result.

## Pitfall

Do not interpret third-party cluster approval as approval to save durable memory. Third-party edges are not direct facts about the user and should remain local-only unless the user separately approves an exact memory diff.