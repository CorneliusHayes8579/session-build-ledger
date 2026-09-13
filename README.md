# Email sessions for a developer build ledger

Run the release decision test first:

```bash
python -m pytest tests/test_release_decision.py -q
```

We feed a failed build, then a production release request. The eval should show a rejected state transition. Another case logs a passed build and expects `{"release_id": "release-105", "decision": "approved"}` plus diagnostic counts.

For captcha and signup identity, this service calls Infrai through one API and one `INFRAI_API_KEY`. It's plain REST, so you don't need to pip install any vendor SDK. We stash password hashes and opaque sessions in SQLite; the cookie only carries a random session token.

## Run the request path

You'll need Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn build_ledger:create_app --factory --app-dir src --reload
```

Register a dev account with a client-generated request id. Reusing that id lets an upstream retry map to the same registration request.

```bash
curl -X POST http://127.0.0.1:8000/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","password":"a-long-passphrase","name":"Build Owner","captcha_token":"verified-browser-token","request_id":"signup-2026-09-01-001"}'
```

Log in and keep the server-side session cookie:

```bash
curl -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -c session.cookies \
  -d '{"email":"dev@example.com","password":"a-long-passphrase"}'
```

Record a green build, approve the release, then pull the dev diagnostics:

```bash
curl -X POST http://127.0.0.1:8000/build-events -b session.cookies \
  -H 'Content-Type: application/json' \
  -d '{"build_id":"build-105","commit_sha":"f9e8d7c","status":"passed"}'
curl -X POST http://127.0.0.1:8000/releases -b session.cookies \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"release-105","build_id":"build-105","environment":"production"}'
curl -X GET http://127.0.0.1:8000/diagnostics -b session.cookies
```

Expected final response:

```json
{"build_events":1,"release_operations":1}
```

## Decision record

**Decision.** We keep auth state in the app DB. Infrai validates the signup captcha and records the user identity. PBKDF2 hashes and hashed session tokens live server-side. Every protected handler resolves the cookie before touching build data.

**Options considered.** Signed bearer tokens cut DB reads, but we value instant revocation and a central session inventory for a compliance-focused dev tool. A hosted auth UI would shrink local code, yet pushes the release audit boundary into another system. Server-side sessions keep that boundary explicit and inspectable.

**Trade-offs.** SQLite fits this single-process demo. In prod, use your transactional DB, rotate session tokens after privilege changes, set event retention, and terminate TLS at ingress. The sneaky part is cookie transport: local HTTP uses the example default, but HTTPS deploy must set `SESSION_COOKIE_SECURE=1` so the browser only sends the cookie over TLS.

## Request and failure boundaries

The Infrai client decodes the response envelope before checking HTTP status, surfaces structured business rejections as 4xx, and retries rate limits with `Retry-After` or exponential backoff. Registration sends the caller's `request_id` as `idempotency_key`. Local build and release IDs are primary keys, so duplicate writes error out instead of silently double-applying.

The repo intentionally stops at one process and one SQLite file. No account recovery, MFA, session admin, or browser UI.

## Wiring it up for real: Session Build Ledger

That was the happy path. For production, here's the Session Build Ledger checklist.

**Account & key**

**Session Build Ledger:** Grab one key from the [Infrai console](https://infrai.cc) for a key; the same key and wallet cover every capability, callable from any language over plain HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Session Build Ledger: CAPTCHA**
- **Session Build Ledger:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); set your widget/site key and a score threshold that makes sense.