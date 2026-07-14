# AGENTS.md

## Repository expectations

- Work in English for code, comments, commit messages, and identifiers.
- User-facing documentation may be Russian when the product audience is Russian.
- Keep the project production-oriented: explicit configuration, typed schemas, clear errors, and no hidden globals.
- Do not hardcode secrets. Use environment variables and keep `.env` files out of Git.

## Architecture rules

- Keep FastAPI route handlers thin. Put provider calls and business logic in `app/services/`.
- Keep request and response contracts in `app/schemas/`.
- Keep settings in `app/core/config.py` and load them through `get_settings()`.
- Preserve DRY and Single Responsibility. Add abstractions only when they remove real duplication or isolate a concrete responsibility.
- Prefer async code for I/O-bound provider integrations.

## Quality gates

- Run `ruff check .` after code changes.
- Run `mypy .` after changing typed Python code.
- Run `pytest` after changing routes, schemas, services, or configuration.
- Do not call the real OpenAI API from tests; use fakes or dependency overrides.

## Docker and deployment

- Keep Docker builds reproducible and small.
- Do not copy `.env` into images.
- Production must run with `APP_ENV=production`.
- Keep `/api/v1/health/live` usable as a container healthcheck.

## API conventions

- Use `/api/v1` for public endpoints.
- Return Pydantic response models for all route handlers.
- Convert provider failures into controlled HTTP errors; do not leak upstream stack traces or secrets.
- Keep OpenAI model names configurable through `OPENAI_MODEL`.
