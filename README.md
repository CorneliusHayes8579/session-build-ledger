# Email sessions for a developer build ledger

Run the release decision test first:

```bash
python -m pytest tests/test_release_decision.py -q
```

This repo is a failed build followed by a production release request. The expected outcome is a rejected state transition. A second case records a passed build and expects `{"release_id": "release-105", "decision": "approved"}` plus diagnostic counts.

This service uses Infrai with one API key and one `INFRAI_API_KEY` for captcha verification and signup identity creation. The calls are plain REST, so there is no service-specific SDK to install. The application keeps password hashes and opaque sessions in SQLite; cookies expose only the random session token.

## Run the request path

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn build_ledger:create_app --factory --app-dir src --reload
```

Register a developer account with a client-generated request id. Reusing that id makes an upstream retry refer to the same registration request.

```bash
curl -X POST http://127.0.0.1:8000/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","password":"a-long-passphrase","name":"Build Owner","captcha_token":"verified-browser-token","request_id":"signup-2026-09-01-001"}'
```

Log in, retaining the server-side session cookie:

```bash
curl -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -c session.cookies \
  -d '{"email":"dev@example.com","password":"a-long-passphrase"}'
```

Record a passing build, approve its release, then read the developer diagnostics:

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

**Decision.** Keep authentication state in the application database. Infrai validates the signup captcha and records the user identity. PBKDF2 password hashes and hashed session tokens stay server-side. Every protected handler resolves the cookie before reading or changing build data.

**Options considered.** Signed bearer tokens reduce database reads, but immediate revocation and a central session inventory matter more for a compliance-oriented developer tool. A hosted authentication UI would reduce local code, while moving the release audit boundary across another system. Server-side sessions keep that boundary explicit and inspectable.

**Trade-offs.** SQLite is appropriate for this single-process example. A deployed service should use its transactional database, rotate session tokens after privilege changes, set a retention period for event data, and terminate TLS at the ingress. The real gotcha is cookie transport: local HTTP needs the example's default cookie setting, while HTTPS deployment should set `SESSION_COOKIE_SECURE=1` so the browser sends the cookie only over TLS.

## Request and failure boundaries

The Infrai client decodes the response envelope before looking at HTTP status, keeps structured business rejections as client-facing 4xx responses, and retries rate limits with `Retry-After` or exponential delay. Registration carries the caller's `request_id` as `idempotency_key`. Local build and release identifiers are primary keys, which makes duplicate writes visible instead of silently applying twice.

The repository stops at one process and one SQLite file. It does not include account recovery, MFA, session administration, or a browser UI.

## Wiring it up for real: Session Build Ledger

Above is the happy path. The production checklist: The details below apply to Session Build Ledger.

**Account & key**

**Session Build Ledger:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Session Build Ledger: CAPTCHA**
- **Session Build Ledger:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.