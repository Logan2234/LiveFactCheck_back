---
paths:
  - "**/*.py"
---

# Python & FastAPI conventions

Generic best practices for any Python/FastAPI code. Project-specific facts (commands,
admin contract, gotchas) live in CLAUDE.md, not here.

## Types
- Annotate everything: function params and return types, not just locals.
- Use modern syntax: `list[str]`, `dict[str, int]`, `str | None` — not `List`, `Optional`.
- Never use a mutable default argument (`def f(x: list = [])`); default to `None` and build inside.
- Typing drives FastAPI's validation and docs — treat it as load-bearing, not decoration.

## Pydantic & validation
- Never validate input by hand. Declare a Pydantic model and type the param; FastAPI returns 422 on its own.
- Put constraints in the type: `Field(gt=0)`, `Field(max_length=...)`, `EmailStr`, `HttpUrl`.
- Cross-field or conditional checks go in `field_validator` / `model_validator`.
- Separate input and output schemas (Base / Create / Read). Never return a schema that exposes secrets (password hash, token).
- Set `response_model` (or a return type) on routes — it filters the output, it's a leak guard, not just docs.

## Async vs blocking
- A blocking call inside an `async def` route freezes the whole event loop for every request.
- In an async route, everything must be non-blocking. Offload blocking/CPU-bound work with `await asyncio.to_thread(...)` or `run_in_executor`.
- Use async clients (`httpx`) in async code, never a sync client (`requests`).
- For long post-response work, use `BackgroundTasks` or a real worker, not the request itself.

## Errors & robustness
- Never swallow errors: no bare `except:` or `except Exception: pass`. Catch the most specific exception, then handle it or let it propagate.
- Raise `HTTPException` for expected API errors; register a global exception handler for recurring business errors instead of repeating translation in every route.
- Use context managers (`with`) for anything that must be closed: files, sessions, connections.

## Dependencies
- Use `Depends` for shared resources (DB session, current user, auth) instead of fetching them inside each route.
- DB sessions go through a `get_db` dependency that `yield`s and closes in a `finally`.

## Config & secrets
- No secret or tunable hardcoded in code. Centralize in a pydantic-settings `Settings` validated at startup.
- A missing required env var must fail startup, not crash on first request.
- `.env` is never committed; only a `.env.example` with no real values.

## Logging
- Use the `logging` module, never `print`, so verbosity is configurable per environment.
- Never log sensitive data (passwords, tokens, keys).

## Idiomatic Python
- Iterate over objects directly (`for item in items`), not indices; use `enumerate` when you need the index.
- Prefer f-strings and `pathlib` over string concatenation for formatting and paths.
- List comprehensions for simple transforms only — drop back to a loop if it gets nested/unreadable.
- Comment the *why*, not the *what*. A clear, well-typed function needs few comments.

## Tooling
- Format & lint with `ruff`; type-check with `mypy` or `pyright`. Fix type errors, don't ignore them.
- Pin dependencies in `pyproject.toml`.

## Tests
- pytest, with FastAPI's `TestClient` (or `httpx.AsyncClient`) — no real port needed.
- Override dependencies in tests via `app.dependency_overrides` (e.g. a test DB).
- Test services (pure logic) first, then a few integration tests on routes.