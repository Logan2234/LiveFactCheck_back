---
paths:
  - "**/*.py"
---

# Architecture & layering

Where each kind of code lives and how the layers relate. This describes the target layout
for any non-trivial FastAPI service. The README documents the *current* tree — read it for
the actual state; this rule is the convention to follow when adding or moving code.

## Layer responsibilities

A request flows through one layer per concern, each with a single job:

`route → schema (validate) → service (business logic) → model/db → schema (serialize out)`

- **Routes** (`api/routers/`) — HTTP only. Receive, validate via types, call a service, return. No business logic, no SQL.
- **Schemas** (`schemas/`) — Pydantic models = the API input/output contract.
- **Services** (`services/`) — business logic. Plain Python in, plain Python out; no knowledge of HTTP.
- **Models** (`models/`) — ORM models = database tables (only if there's a DB).
- **Core/db/config** — cross-cutting: settings, security, DB session.

The guiding rule is separation of concerns: a route never holds business logic, a service never knows about HTTP.

## Folder layout

```
app/
├── main.py            # FastAPI app, router mounting, middleware
├── config.py          # pydantic-settings Settings, loaded from env
├── dependencies.py    # shared deps (get_db, get_current_user…)
├── api/routers/       # one file per resource (users.py, items.py)
├── schemas/           # Pydantic request/response models
├── models/            # ORM models (DB tables), if any
├── services/          # business logic
├── db/                # engine, session, declarative base
└── core/              # security, hashing, JWT, shared utils
```

- Never put routes, logic, or config inline in `main.py` — it only assembles the app.
- One `APIRouter` per resource, with `prefix` and `tags`, mounted in `main.py` via `include_router`.
- For a large project, a per-domain layout (a `users/` folder holding its own router/schemas/service/models) is an alternative — but keep the same separation either way.

## Hard boundaries

- ORM models and Pydantic schemas are distinct, in distinct folders, even when they look alike. Convert explicitly (`model_config = {"from_attributes": True}`); never serve an ORM object straight from a route.
- Business errors are raised by services as neutral exceptions; the API layer maps them to HTTP status codes. The HTTP boundary stays in the route layer.
- Services must be runnable and testable without a web server.