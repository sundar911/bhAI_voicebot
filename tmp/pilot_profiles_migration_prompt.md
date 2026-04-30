# Task: Move user profiles onto the Railway volume, scoped to actual users

## Background

bhAI has a user-profile system: per-artisan context files (phone-numbered, Fernet-encrypted) that get injected into the system prompt as `=== User Profile ===` so bhAI walks into every conversation already knowing name, workshop, family size, etc.

**The current system is broken in production.** `scripts/extract_profiles.py` dumps ~200 profiles from the TM HR Excel into `knowledge_base/users/`, which is **gitignored** — so in production on Railway, there are zero profiles, and `load_user_profile()` returns `""` for every user. bhAI currently learns names purely from conversation history.

See `ARCHITECTURE.md` §13 and `CLAUDE.md` (User profiles section) for current state.

## Goal

Profiles should:
1. Live on the Railway volume at `/app/data/users/` (same volume that holds `conversations.db` at `/app/data/`)
2. Exist ONLY for users who have actually interacted with bhAI (not every TM employee — blast radius minimization)
3. Stay Fernet-encrypted at rest with the same `BHAI_ENCRYPTION_KEY`
4. Still work for local development (fall back to `knowledge_base/users/`)

## Design

### 1. New config path

In `src/bhai/config.py`, add alongside the existing path constants:

```python
USERS_DIR = DATA_DIR / "users"   # Railway volume in prod; local ./data/users/ in dev
```

### 2. Update `load_user_profile`

In `src/bhai/llm/base.py` (around line 94), change `load_user_profile` to check the volume path first, then fall back to the knowledge_base path:

```python
def load_user_profile(self, phone: str) -> str:
    """Load and decrypt user profile. Prefers volume path (prod) over KB path (local dev)."""
    from ..config import USERS_DIR
    from ..security.crypto import decrypt_text

    for path in (USERS_DIR / f"{phone}.md", self.kb_dir / "users" / f"{phone}.md"):
        raw = _read_file(path)
        if not raw:
            continue
        try:
            return decrypt_text(raw)
        except Exception:
            return raw  # plaintext fallback for _template.md / manual edits
    return ""
```

Make sure `USERS_DIR` is created at startup — add to `twilio_webhook.py` lifespan or wherever other `DATA_DIR` subdirs get created.

### 3. Upload endpoint (admin)

In `inference/webhooks/twilio_webhook.py`, add a new endpoint next to `/admin/phones`:

```python
@app.post("/admin/profiles/{phone}")
async def admin_upload_profile(phone: str, request: Request, key: str = ""):
    _check_dashboard_key(key)
    # Validate phone format: +91XXXXXXXXXX
    if not re.fullmatch(r"\+91\d{10}", phone):
        raise HTTPException(400, "Invalid phone format")
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty body")
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    (USERS_DIR / f"{phone}.md").write_bytes(body)
    return {"ok": True, "phone": phone, "bytes": len(body)}
```

Same auth pattern as the other admin endpoints (key query param). Accepts the raw Fernet ciphertext as the body — don't re-encrypt on the server side.

### 4. Upload script (client-side)

Create `scripts/upload_pilot_profiles.py` that:
1. Takes a BASE_URL and admin key from args/env
2. Calls `GET /admin/phones` to get the list of phone numbers that have interacted with bhAI
3. For each phone, reads `knowledge_base/users/{phone}.md` locally
4. POSTs the encrypted body to `/admin/profiles/{phone}` on the Railway deployment
5. Reports uploaded / skipped (if no local file) / failed counts

Skip any phone whose local file doesn't exist — don't manufacture profiles.

### 5. Tests

Update `src/tests/test_llm_base.py`:
- Test `load_user_profile` reads from `USERS_DIR` when present (use `monkeypatch` on `bhai.config.USERS_DIR`)
- Test falls back to `kb_dir / "users"` when volume path is empty
- Test returns `""` when neither path has the file
- Test decryption failure falls through to plaintext (existing behavior)

Add a test for the new endpoint in `src/tests/test_webhook.py`:
- Missing key → 403
- Invalid phone format → 400
- Empty body → 400
- Valid call → file written to `USERS_DIR`

### 6. Rollout

After merging + Railway auto-deploys:
1. `curl "https://bhaivoicebot-production.up.railway.app/admin/phones?key=bhai-pilot-2026"` to confirm the pilot users list (should be the 5 pilot + a couple of non-pilot testers)
2. Run `uv run python scripts/upload_pilot_profiles.py --base-url https://bhaivoicebot-production.up.railway.app --key bhai-pilot-2026`
3. Spot-check with `/debug/{phone_hash}?key=...` — the response should now include the decrypted profile content

## Files to touch

- `src/bhai/config.py` — add `USERS_DIR`
- `src/bhai/llm/base.py` — update `load_user_profile`
- `inference/webhooks/twilio_webhook.py` — add `/admin/profiles/{phone}` endpoint; ensure `USERS_DIR` created on startup
- `scripts/upload_pilot_profiles.py` — new client-side upload script
- `src/tests/test_llm_base.py` — tests for new load path
- `src/tests/test_webhook.py` — tests for new endpoint
- `ARCHITECTURE.md` §13 — change the intended-row to current-row once shipped
- `CLAUDE.md` User profiles section — drop the "pre-migration" caveat once shipped

## Constraints

- DO NOT commit any real encrypted profile files to git. The `.gitignore` rule at line 49 must stay.
- DO NOT change the Fernet encryption scheme — reuse `src/bhai/security/crypto.py` as-is.
- DO NOT expand the allowlist in `extract_profiles.py`. Religion/caste/disability/loans/income/health must stay blocked.
- The admin upload endpoint is dual-use (could overwrite existing profiles). Consider whether to reject overwrites or log them.
- `/admin/profiles/{phone}` takes a raw phone number (`+91XXX`), not a phone_hash. That's correct — the filename scheme is phone-based. Just make sure the logs use `_phone_hash()` for the phone, never the raw number.

## Verification

Before reporting done, confirm:
1. `uv run pytest src/tests/` passes (79+ tests)
2. Locally: create a test profile at `data/users/+919999999999.md`, ensure `load_user_profile("+919999999999")` returns the decrypted content
3. Locally: remove the volume file, confirm fallback to `knowledge_base/users/` still works
4. On Railway after deploy: upload one profile via the script, hit `/debug/{hash}` and see it reflected
5. Check that no raw phone numbers appear in any log output

## Out of scope (don't do these)

- Runtime profile updates (bhAI learning new facts and rewriting the profile). That's a separate feature — for now profiles are write-once via the upload endpoint.
- Migrating off `scripts/extract_profiles.py` for local dev — it still serves the "populate all employees locally for testing" use case.
- Adding a profile deletion endpoint. User-initiated deletion would be handled separately (GDPR-style request).
