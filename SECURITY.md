# Security Policy — LiveFactChecker backend

FastAPI service: audio over WebSocket → `faster-whisper` transcription →
claim verification via the Anthropic API. This is the component that holds the
secrets and talks to third-party services, so treat it as the trust boundary.

## Supported versions

Only the latest `main` is supported. There are no maintained release branches;
fixes land on `main` and you should deploy from there.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

- Preferred: open a private [GitHub Security Advisory](https://github.com/Logan2234/LiveFactCheck_back/security/advisories/new).
- Or email **logan.w@sfr.fr** with steps to reproduce and impact.

Expect an acknowledgement within a few days. Please give a reasonable window to
ship a fix before any public disclosure.

## Security model & configuration

Secrets are read from `.env` (see `app/config.py`) and startup **fails fast** if
they are missing — `ANTHROPIC_API_KEY`, `ADMIN_PASSWORD` and `JWT_SECRET` are all
required. None of these belong in version control.

- **`.env` must never be committed.** It carries the Anthropic key and the admin
  credentials/JWT signing secret.
- **`JWT_SECRET`** signs both admin and user tokens (HS256). Use a long random
  value; rotating it invalidates every issued token. Admin and user tokens share
  the secret but are separated by a `type` claim (`app/core/security.py`), so a
  user token can never satisfy an admin-gated route.
- **`ADMIN_PASSWORD`** is checked in constant time (`hmac.compare_digest`).
- **`ALLOWED_ORIGINS`** drives CORS — keep it to the exact front-end origins in
  production; never widen it to `*`.
- **`DATABASE_URL`** defaults to a local SQLite file (`livefactchecker.db`). That
  file holds persisted sessions, transcripts, verified claims and user records —
  do not commit it and restrict filesystem access.

## Hardening already in place

- `/admin/login` is rate-limited per client IP (`app/core/rate_limit.py`,
  `LOGIN_RATE_LIMIT_*`) to slow brute force. Note the limiter is process-local
  in-memory: it resets on reload and is **not** shared across instances.
- User passwords are hashed with Argon2 (`app/core/passwords.py`).
- The `/ws` audio stream has guardrails: `MAX_AUDIO_BYTES` caps a single frame,
  and `MAX_CONCURRENT_SESSIONS` / `MAX_SESSION_DURATION_SECONDS` bound cost and
  load (both default to `0` = disabled for local dev — **set them in prod**).

## Known limitations (by design, single-instance local service)

- The rate limiter and any in-process caches are per-process; running multiple
  instances behind a load balancer weakens both. Add a shared store first.
- There are no DB migrations — the schema is created with `create_all` only.
  Adding a column to an existing table can break deployed databases.
- User JWTs are stored client-side in `localStorage`, so they are exposed to any
  XSS on the front-end. Keep token lifetime (`JWT_EXPIRE_HOURS`) modest.

## Scope

In scope: authentication/authorization on `/admin/*`, `/auth`, `/users` and
`/sessions`; the `/ws` and `/admin/whisper/transcribe` audio paths; secret and
CORS handling; injection into stored/exported data. Out of scope: the security of
the upstream Anthropic API and the `faster-whisper`/`ctranslate2` model runtime.
