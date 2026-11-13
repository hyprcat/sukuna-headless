# Sukuna Backend

Django 6 + Strawberry GraphQL API. See `../../docs/BACKEND_CODING_STANDARDS.md` for the rules
that apply to every change here.

## First-time setup

```bash
cp .env.example .env                 # then edit SECRET_KEY at minimum
uv sync                              # installs runtime + dev deps
uv run manage.py migrate             # requires Postgres reachable per DATABASE_URL
uv run manage.py createsuperuser     # admin login
uv run manage.py runserver           # http://localhost:8000
```

GraphQL endpoint: `POST /graphql/`. Admin: `/admin/` (Unfold theme).

## Day-to-day

```bash
uv run manage.py <cmd>     # any Django management command
uv run pytest              # tests (uses config.settings.test)
uv run ruff check .        # lint, including the §3 size caps
uv run ruff format .       # format
uv run mypy .              # strict on models/ and services/
```

## Layout

```
config/                    # Django project package
  settings/{base,dev,prod,test}.py
  runtime.py               # pydantic-settings — the only place env vars are read
  schema.py                # Strawberry root schema (assembled from app schemas)
  urls.py
apps/                      # business apps land here (one folder per bounded context)
  <app>/
    models/                # fat models — domain logic lives here
    api/                   # Strawberry types/resolvers — auth + delegate, ≤20 lines each
    services/              # cross-aggregate orchestration only
    tasks/                 # django.tasks wrappers
    schemas/               # pydantic DTOs for non-GraphQL boundaries
    admin/                 # Unfold ModelAdmin + custom actions
```

Per the standards: no ORM in resolvers, mutations return `MutationResult`, file size 150–300
lines, function size ≤20 lines.
