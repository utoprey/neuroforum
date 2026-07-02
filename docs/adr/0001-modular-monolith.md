# ADR 0001 — Modular monolith over microservices

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** project owner + Claude
- **Supersedes:** —

## Context

The forum is a greenfield project with these constraints relevant to the
architectural shape:

- **Team size: 1–2 humans + LLM agents.** No dedicated platform / SRE team.
  Operational overhead has to be near-zero.
- **Domain has heavy cross-module read/write transactions.** Posting an
  article touches `articles`, `article_revisions`, `mentions`,
  `notifications`, `user_stats`, `audit_log`. Posting a message updates
  `messages`, parent's `comment_count`, `mentions`, `notifications`,
  `user_stats`. Doing this across service boundaries means sagas or
  outbox patterns — premature for the current scale.
- **No independent deployability requirement.** All modules ship together
  on the same release cadence. There is no module that has a different
  scaling profile severe enough to justify isolation today.
- **All modules share the same runtime characteristics:** async Python,
  same DB, same Redis, same RabbitMQ.
- **MCP server and Dramatiq worker DO need separate processes** — but
  they import from the same Python package, not from a separate service.

## Decision

We build a **modular monolith**:

- One FastAPI process exposes the HTTP API.
- One Dramatiq worker process consumes the same Python package's tasks.
- One MCP server process exposes the same package's tools to agents.
- One Postgres, one Redis, one RabbitMQ, one MinIO.

Code is organized under `backend/app/modules/<domain>/`, where each
module owns:

```
app/modules/<domain>/
  __init__.py
  models.py          # SQLAlchemy ORM, registered on the shared Base
  schemas.py         # Pydantic Create/Update/Read
  repository.py      # data access (optional thin layer)
  service.py         # business logic, transactions, RBAC checks
  router.py          # FastAPI APIRouter (mounted at /api/v1/<domain>)
  workers.py         # Dramatiq actors (optional)
  events.py          # internal pub/sub hooks (optional)
  tests/             # module-local tests
```

**Isolation rule:** cross-module calls go through the *other module's
service layer*. Reaching directly into another module's `models.py` or
`repository.py` is forbidden. This keeps the seams clean enough that any
module could later be peeled off into its own service if scale forces it.

### Coordination pattern: autodiscovery, not central registry

The two cross-cutting concerns where modules would normally have to edit
a shared file — router mounting and Alembic model discovery — are
solved by **pkgutil-based autodiscovery**, so adding a new module
requires zero edits to shared files.

**Router mounting** (`backend/app/api/v1/router.py`):

```python
def build_api_router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")
    for module_info in pkgutil.iter_modules(app.modules.__path__):
        if not module_info.ispkg:
            continue
        try:
            module = importlib.import_module(
                f"app.modules.{module_info.name}.router"
            )
        except ModuleNotFoundError:
            continue  # module has no HTTP surface — fine
        router = getattr(module, "router", None)
        if router is not None:
            api.include_router(router, prefix=f"/{module_info.name}",
                               tags=[module_info.name])
    return api
```

**Alembic model discovery** (`backend/alembic/env.py` — and mirrored in
`backend/tests/conftest.py::_discover_module_models`):

```python
for module_info in pkgutil.iter_modules(app.modules.__path__):
    if not module_info.ispkg:
        continue
    try:
        importlib.import_module(f"app.modules.{module_info.name}.models")
    except ModuleNotFoundError:
        continue
```

This is the contract: **a module is fully integrated the moment its
directory exists under `app/modules/`** with the conventional file
names. No central manifest to update, no merge conflicts on a shared
import list when two module agents work in parallel.

## Consequences

### Positive

- **Multi-table transactions are trivial.** `async with session.begin():`
  spans `articles` + `mentions` + `notifications` + `audit_log` writes
  with ACID guarantees. No sagas, no outbox, no compensating actions.
- **One deployment, one logs stream, one tracing context.** Debugging a
  cross-module bug doesn't require correlating across service
  boundaries.
- **Refactoring across modules stays cheap** until the service-layer
  contract is the only thing crossing the boundary.
- **Module agents work independently.** Because autodiscovery removes the
  need to edit shared files, two agents writing two modules in parallel
  almost never produce merge conflicts.

### Negative

- **One deploy = everything redeploys.** A hotfix in the `agents` module
  bounces the same process that serves `articles`. Acceptable while we
  have minutes of downtime budget; revisit if SLA tightens.
- **Per-module scaling is impossible.** If `search` becomes CPU-bound we
  can't scale only its replicas — we scale the whole API. Mitigation:
  heavy work already goes to Dramatiq workers, which DO scale
  independently (we can run more worker replicas without touching the
  API).
- **Discipline-based isolation.** Nothing physically prevents
  `forum.service` from importing `articles.repository`. We rely on code
  review + a future import-linter rule.

### Neutral

- The eventual split into services is still possible because the
  service-layer-only rule keeps internal contracts narrow. But we're not
  paying for that flexibility upfront.

## Alternatives considered

### Microservices

Rejected. The cost — service discovery, distributed tracing, sagas for
multi-table writes, separate deploy pipelines, network failure modes
between modules that conceptually never fail apart — is enormous
relative to the team size and current scale. The only argument for
microservices here is "future-proofing", which is the wrong tradeoff
when the future load is unknown and the present headcount is tiny.

### Single flat package (no modules)

Rejected. Even at MVP scope we have ~12 conceptual modules. Without
explicit module boundaries the codebase tangles into a ball of mud
within weeks, and onboarding LLM agents to "the right place to put
this" becomes impossible.

### Hexagonal / clean architecture with strict ports-and-adapters

Rejected as overkill. We adopt the spirit (service layer, no SQL in
routers, Protocols for swappable backends like `SearchEngine`) without
the ceremony of separate ports/adapters/domain packages per module.

## References

- `backend/app/main.py` — app factory, router mount point
- `backend/tests/conftest.py::_discover_module_models` — mirror of the
  alembic autodiscovery used in tests
- `CLAUDE.md` § Architecture principles
