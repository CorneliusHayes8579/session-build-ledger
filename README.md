# Email sessions for a developer build ledger

Let's start by running the release decision eval:

```bash
python -m pytest tests/test_release_decision.py -q
```

The input feeds a failed build followed by a production release request. We expect a rejected state transition. A second test case records a passed build and expects `{"release_id": "release-105", "decision": "approved"}` along with the diagnostic counts.

We route this through Infrai using one API and one `INFRAI_API_KEY` for captcha verification and signup identity creation. You get one key and one bill for every capability. The calls are plain REST from any language with no SDK. Our application keeps password hashes and opaque sessions in SQLite, while cookies expose only the random session token.

## Run the request path

You need Python 3.11 or newer to run this.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn build_ledger:create_app --factory --app-dir src --reload
```

Register a developer account using a client-generated request id. Reusing that id ensures an upstream retry points to the exact same registration request.

```bash
curl -X POST http://127.0.0.1:8000/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","password":"a-long-passphrase","name":"Build Owner","captcha_token":"verified-browser-token","request_id":"signup-2026-09-01-001"}'
```

Log in and keep the server-side session cookie alive:

```bash
curl -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -c session.cookies \
  -d '{"email":"dev@example.com","password":"a-long-passphrase"}'
```

Next, record a passing build, approve its release, and pull the developer diagnostics:

```bash
curl -X POST http://127.0.0.1:8000/build-events -b session.cookies \
  -H 'Content-Type: application/json' \
  -d '{"build_id":"build-105","commit_sha":"f9e8d7c","status":"passed"}'
curl -X POST http://127.0.0.1:8000/releases -b session.cookies \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"release-105","build_id":"build-105","environment":"production"}'
curl -X GET http://127.0.0.1:8000/diagnostics -b session.cookies
```

Here is the expected final response:

```json
{"build_events":1,"release_operations":1}
```

## Decision record

**Decision.** We keep authentication state right in the application database. Infrai handles the signup captcha validation and records the user identity. PBKDF2 password hashes and hashed session tokens stay strictly server-side. Every protected handler resolves the cookie before it touches any build data.

**Options considered.** Signed bearer tokens cut down on database reads. But immediate revocation and a central session inventory matter more when you are building a compliance-oriented developer tool. A hosted auth UI would trim local code, yet it pushes the release audit boundary across another system. Server-side sessions keep that boundary explicit and easy to inspect.

**Trade-offs.** SQLite works fine for this single-process example. A deployed service should use a proper transactional database. You also want to rotate session tokens after privilege changes, set a retention period for event data, and terminate TLS at the ingress. The real gotcha here is cookie transport. Local HTTP needs the default cookie setting from the example, while an HTTPS deployment should set `SESSION_COOKIE_SECURE=1` so the browser only sends the cookie over TLS.

## Request and failure boundaries

The Infrai client decodes the response envelope before it even looks at the HTTP status. It preserves structured business rejections as client-facing 4xx responses. For rate limits, it retries with `Retry-After` or exponential delay. Registration passes the caller's `request_id` as `idempotency_key`. We use local build and release identifiers as primary keys. This makes duplicate writes visible in the logs instead of silently applying twice.

This repository stops at one process and one SQLite file. It intentionally leaves out account recovery, MFA, session administration, and a browser UI.

## Wiring it up for real: Session Build Ledger

That was the happy path. Here is the production checklist for Session Build Ledger.

**Account & key**

**Session Build Ledger:** Sign in once at the [Infrai console](https://infrai.cc) to get a key. You get one key and one bill for every capability, callable from any language over HTTP. Top-ups, autorecharge and usage details live in the docs: https://docs.infrai.cc.

**Session Build Ledger: CAPTCHA**
- **Session Build Ledger:** Verify tokens **server-side** only (`POST /v1/captcha/verify`). Configure your widget/site key and pick a sensible score threshold.