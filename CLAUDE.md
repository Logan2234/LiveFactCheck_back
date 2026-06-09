# CLAUDE.md — Backend

LiveFactChecker backend. Cross-component context (WebSocket contract, two-repo layout)
lives in ../CLAUDE.md. README.md documents the stack, env vars, endpoints and structure —
read it for anything descriptive; this file is only conventions and traps.

FastAPI service: audio over `/ws` → local transcription (faster-whisper) → claim
extraction/verification via the Anthropic API. Plus an admin API under `/admin/*`.

## Tracking files (TODO.md, README.md)

- Read them at the start of a task for **direction and intent** — where the project
  is headed and the why behind choices.
- Treat their **progress/done state as a hint, not the truth**: a task marked done
  may not be, or may have drifted. Verify against the code before relying on it. When
  they disagree, **the code wins** — flag the gap, don't edit code to match the docs.
- Update these files **only when I ask** (or at the end of a task I've validated).
  No speculative or routine updates.

## Commands

Own git repo — run git/CI from `backend/`. Default shell is PowerShell 5.1, where `&&`
is a parse error: run statements separately.

- Install: `pip install -e ".[dev]"` (all config — deps + tooling — lives in `pyproject.toml`; no requirements*.txt).
- Run: `python run.py` (localhost:8000, reload + watches .env)
- CI gates (exactly these, on pull_request): `ruff format --check .`, `ruff check .`, `pyright app/`, `pytest`.

Tests live in `tests/`; `conftest.py` sets dummy auth/API env vars before any `app`
import so the suite runs offline (the `ANTHROPIC_API_KEY` validator would otherwise fail).
Test pure service logic first (see `tests/test_claim_extractor.py`), routes later.

## Conventions

- Every route has an explicit Pydantic `response_model`; validate inputs via Pydantic, never raw dicts.

## Admin API

- Everything under `/admin/*` is gated by `require_admin` (`dependencies.py`), which verifies a JWT minted in `core/security.py`. The routes live in `api/routers/` (admin in `admin.py`, the `/admin/login` token exchange in `auth.py`), mounted in `main.py` — read those rather than trusting a list here.
- `extract_and_verify` is the prod path; `debug_extract` mirrors it but also returns token usage / turn count / web_search flags, and powers `/admin/model-test`.

## Gotchas

- Startup fails by design if `ANTHROPIC_API_KEY` is missing or still the `sk-ant-...` placeholder (validator in `config.py`).
- ffmpeg must be on PATH — faster-whisper shells out to it; a missing binary only surfaces at transcription time.
- Transcription is hardcoded to French (`language="fr"`); the system prompt and claim categories are French too.
- Transcripts under `MIN_WORDS` (`claim_extractor.py`) are skipped before any API call.
- The fact-checker forces structured output via the `submit_claims` tool. If the model web-searches but stops before calling it, a second turn forces `tool_choice` = submit_claims. Keep that two-turn fallback if you touch the flow.
- web_search is controlled by tool availability, not prompting: when off, `WEB_SEARCH_TOOL` simply isn't passed.
- `PATCH /admin/config` mutates `settings` in memory (model, log level) at runtime; the change is lost on the next reload and never touches `.env`.
