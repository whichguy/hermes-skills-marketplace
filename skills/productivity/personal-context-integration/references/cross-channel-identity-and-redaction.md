# Cross-Channel Identity Mapping + privacy.redact_pii Compatibility

Reuse the personal-context security graph (circles + `resolve_engagement.py`) as the
identity backbone for messaging platforms (WhatsApp/Telegram groups), instead of
building a parallel system. The graph keys people by stable `person_id`; this adds the
channel-identity bridge and the redaction-aware resolution path.

## The identity bridge (in `people.yaml`)

Add `platform_identities` under each person's `aliases`:

```jsonc
"aliases": {
  "names": ["Kelly Wiese"],
  "emails": ["kelly@example.com"],
  "platform_identities": {
    "whatsapp": ["19253360644"],   // phone or JID, stored digits-only, country code, NO +
    "telegram": ["123456789"]       // STABLE numeric user ID (never the mutable @username)
  }
}
```

`resolve_engagement.py` gained `--whatsapp` / `--telegram` (raw) and normalizes input
(strips `+`, spaces, dashes, `@s.whatsapp.net` / `@c.us` / `@lid` JID suffix, and a
`:device` resource) to digits before matching. Precedence:
`--person-id > whatsapp > telegram > sender_hash > email > name > domain-org`.

## The critical gotcha — privacy.redact_pii starves the raw-number resolver

Jim runs `privacy.redact_pii: true`. WhatsApp/Telegram/Signal/BlueBubbles are in the
gateway's `_PII_SAFE_PLATFORMS` (`gateway/session.py`), so the gateway replaces a
sender's raw id with a **deterministic** token before it ever reaches the model:

```
user_<12hex>  where  12hex = sha256(raw_id).hexdigest()[:12]    # gateway/session.py::_hash_sender_id
```

So the agent NEVER sees the raw phone number at runtime — `--whatsapp 19253360644`
resolution can pass tests but never fire in production. Verify this before assuming a
raw-number resolver works live: check `privacy.redact_pii` and whether the platform is
PII-safe.

## The fix — resolve by the same deterministic hash (`--sender-hash`)

The resolver mirrors the gateway formula in `sender_hash()` and indexes the hash of
every stored raw number (plus optional explicit `whatsapp_hash` / `telegram_hash`
lists). A redacted sender then resolves via:

```
python resolve_engagement.py --sender-hash user_<hex>   # the token the agent actually sees
```

`--sender-hash` also accepts a raw id (it hashes internally). This keeps `redact_pii`
**ON** (privacy preserved) AND makes the layer identity-aware. To populate from a known
number: `sha256("19253360644")[:12]` → `user_8ff6fc5a8c3d`.

All safety invariants apply to the hash path too: ambiguity (same number on two people)
is fail-closed, unknown hash is fail-closed, and the principal lock fail-closes.

## Anti-spoofing principal lock (Jim's explicit requirement)

The principal (`person_id: "jim"`) is a **trust anchor, never an inbound recipient**:

- `resolve_engagement.py` `PRINCIPAL_IDS`: any resolution to the principal — by email,
  name, raw messaging id, OR redacted hash — is forced fail-closed. A spoofed "I'm Jim,
  send me X" can never produce a permissive card.
- `validate_personal_context.py` `PRINCIPAL_LOCKED_EMAILS` / `PRINCIPAL_LOCKED_WHATSAPP`
  / `PRINCIPAL_LOCKED_TELEGRAM`: a principal-owned email/number assigned to any other
  `person_id` is a hard validation error (graph tamper / spoof). Keep the resolver's
  `PRINCIPAL_IDS` and the validator's locked sets in sync.

## Group security model

- Resolve the **requester's** card before answering; never volunteer another circle's
  context (compartmentalization).
- Unknown sender → fail-closed, minimal/deny card. Mixed-circle group → strictest
  intersection of the present circles.
- Native `WHATSAPP_ALLOWED_USERS` answers "can they reach the bot at all"; the resolver
  answers "what may they receive." The gateway does not auto-call the resolver — the
  agent is the enforcement point (PEP), so honor the card in drafting.

## First-sighting capture (propose-only)

When an email/signature reveals a new phone/handle for a known person, propose the exact
`platform_identities` addition for approval (Gate 1) — never auto-write, never infer a
principal identity, then run the validator + `run_personal_context_tests.py`.

## Tests & verification

- `test_identity_mapping.py` (stdlib unittest) covers cross-channel resolution,
  normalization, redacted-hash resolution, similar-name/duplicate ambiguity, unknown
  fail-closed, and the principal lock (resolver + validator).
- One-command rerun: `python3 run_personal_context_tests.py` (validator + all test
  modules + `verify_all.py`, fail-closed).
- Pitfall observed this session: large in-place patches to a test file occasionally
  truncated it to zero bytes; prefer recreating the whole file with a single atomic
  write and immediately re-run the suite to confirm it's intact.
