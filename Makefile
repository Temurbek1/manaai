PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy
PYTEST := .venv/bin/pytest
ALEMBIC := .venv/bin/alembic
REPORT_DELIVERER ?= scripts/deliver_portable_artifact.py
ADMIN_IMAGE_TAG ?= manaai-admin-nextjs:verify

.PHONY: install run up down mana-ai-run mana-ai-docker mana-ai-live-eval admin-dev admin-start admin-format-check admin-no-vite admin-bundle-scan admin-production-smoke admin-docker admin-verify auth-backend-tests auth-frontend-tests auth-security auth-docker auth-verify telegram-auth-smoke migrate migration format-check lint typecheck test demo openapi verify meta-readonly-smoke meta-live-readonly-verify audit-migrations audit-focused audit-security audit-schema audit-dependencies audit-browser audit-postgres audit-verify

install:
	$(PYTHON) -m pip install -e ".[operation,dev]"
	cd admin-ui && npm ci

run:
	.venv/bin/uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000

mana-ai-run:
	.venv/bin/uvicorn app.product_ai_main:create_app --factory --reload --host 0.0.0.0 --port 8000

up:
	@test -f .env || (echo "Missing .env — run: cp .env.example .env and fill in real secrets" && exit 2)
	docker compose up --build -d
	@echo "Stack starting: postgres, migrate, api (http://127.0.0.1:8000), worker, admin (http://127.0.0.1:3000)"
	@echo "Follow logs with: docker compose logs -f"

down:
	docker compose down

mana-ai-docker:
	docker compose -f docker-compose.mana-ai.yml up --build

mana-ai-live-eval:
	@test "$${MANA_AI_LIVE_EVAL:-0}" = "1" || (echo "Set MANA_AI_LIVE_EVAL=1 to enable bounded OpenAI evaluation" && exit 2)
	$(PYTHON) scripts/mana_ai_live_evaluate.py

admin-dev:
	cd admin-ui && FASTAPI_BASE_URL=$${FASTAPI_BASE_URL:-http://127.0.0.1:8000} npm run dev

admin-start:
	cd admin-ui && FASTAPI_BASE_URL=$${FASTAPI_BASE_URL:-http://127.0.0.1:8000} npm run start

migrate:
	$(ALEMBIC) upgrade head

migration:
	@test -n "$(name)" || (echo "Usage: make migration name=description" && exit 2)
	$(ALEMBIC) revision --autogenerate -m "$(name)"

format-check:
	$(RUFF) format --check .

admin-format-check:
	cd admin-ui && npm run format:check

lint:
	$(RUFF) check .
	cd admin-ui && npm run lint

typecheck:
	$(MYPY) .
	cd admin-ui && npm run typecheck

test:
	$(PYTEST) -q -m "not live_meta"
	cd admin-ui && npm run test -- --runInBand

demo:
	$(PYTEST) -q tests/test_operation_e2e.py -s

openapi:
	cd admin-ui && npm run generate:api

verify: format-check admin-format-check lint typecheck test
	cd admin-ui && npm run build
	cd admin-ui && npm audit --audit-level=high

admin-no-vite:
	scripts/check_no_vite.sh

admin-bundle-scan:
	$(PYTHON) scripts/admin_bundle_scan.py

admin-production-smoke:
	scripts/admin_production_smoke.sh

admin-docker:
	docker build --build-arg FASTAPI_BASE_URL=http://api:8000 --tag $(ADMIN_IMAGE_TAG) admin-ui

admin-verify: audit-schema admin-format-check
	cd admin-ui && npm run lint
	cd admin-ui && npm run typecheck
	cd admin-ui && npm run test -- --runInBand
	cd admin-ui && npm run build
	$(MAKE) admin-bundle-scan
	$(MAKE) admin-production-smoke
	cd admin-ui && npm audit --audit-level=high
	$(PYTHON) scripts/secret_scan.py
	$(MAKE) admin-no-vite
	$(MAKE) audit-browser
	$(MAKE) admin-docker

auth-backend-tests:
	$(PYTEST) -q tests/test_telegram_auth.py tests/test_telegram_auth_api.py tests/test_telegram_auth_config.py tests/test_telegram_sender.py tests/test_secret_redaction.py tests/test_architecture_boundaries.py tests/test_security.py

auth-frontend-tests:
	cd admin-ui && npm run test -- --runInBand src/components/LoginPanel.test.tsx src/components/AdminShell.test.tsx src/features/UsersPage.test.tsx src/features/ApprovalsPage.test.tsx

auth-security:
	$(PYTHON) scripts/secret_scan.py
	$(PYTEST) -q tests/test_telegram_auth_api.py tests/test_telegram_sender.py tests/test_secret_redaction.py
	@! rg -n 'X-MANA-Actor-ID|X-MANA-Role|X-API-Key' admin-ui/src/api/client.ts admin-ui/src/components/LoginPanel.tsx
	@! rg -n 'Internal API key|Development actor ID|Development role' admin-ui/src/components/LoginPanel.tsx

auth-docker:
	docker build --tag manaai-api:auth-verify .
	$(MAKE) admin-docker

auth-verify: audit-migrations format-check
	$(RUFF) check .
	$(MYPY) .
	$(MAKE) auth-backend-tests
	$(MAKE) admin-format-check
	cd admin-ui && npm run lint
	cd admin-ui && npm run typecheck
	$(MAKE) auth-frontend-tests
	cd admin-ui && npm run build
	$(MAKE) audit-browser
	$(MAKE) auth-security
	$(MAKE) audit-dependencies
	$(MAKE) auth-docker

telegram-auth-smoke:
	@test "$${MANA_TELEGRAM_AUTH_SMOKE:-0}" = "1" || (echo "Set MANA_TELEGRAM_AUTH_SMOKE=1 for this manual check" && exit 2)
	@test -n "$${MANA_TELEGRAM_AUTH_SMOKE_USER_ID:-}" || (echo "Set MANA_TELEGRAM_AUTH_SMOKE_USER_ID explicitly" && exit 2)
	$(PYTHON) scripts/telegram_auth_smoke.py

meta-readonly-smoke:
	$(PYTHON) scripts/meta_readonly_smoke.py --confirm-read-only

meta-live-readonly-verify: audit-verify
	@if [ "$${META_LIVE_READONLY_VERIFY:-0}" = "1" ]; then \
		OPERATION_ADS_PROVIDER=meta $(PYTEST) -q -m live_meta tests/test_meta_live_optin.py && \
		OPERATION_ADS_PROVIDER=meta $(PYTHON) scripts/meta_live_readonly_verify.py && \
		META_LIVE_READONLY_VERIFY=1 scripts/admin_live_readonly_smoke.sh && \
		$(PYTHON) $(REPORT_DELIVERER) \
			--input docs/artifacts/meta-live-readonly-report.artifact.json \
			--output docs/artifacts/meta-live-readonly-report.html && \
		scripts/portable_report_smoke.sh; \
	else \
		echo "Live Meta section skipped: set META_LIVE_READONLY_VERIFY=1 to enable bounded GET-only validation."; \
	fi

audit-migrations:
	scripts/sqlite_migration_audit.sh

audit-focused:
	$(PYTEST) -q tests/test_architecture_boundaries.py tests/test_scheduler_concurrency.py tests/test_action_recovery.py tests/test_operation_repository.py tests/test_secret_redaction.py tests/test_meta_operation_adapter.py
	$(PYTHON) scripts/mutation_audit.py

audit-security:
	$(PYTHON) scripts/secret_scan.py
	$(PYTHON) scripts/quality_marker_scan.py
	docker compose config --quiet

audit-schema:
	scripts/check_openapi_sync.sh

audit-dependencies:
	.venv/bin/pip-audit
	cd admin-ui && npm audit --audit-level=high

audit-browser:
	scripts/browser_e2e.sh

audit-postgres:
	scripts/postgres_audit.sh

audit-verify: verify audit-focused audit-security audit-schema audit-migrations audit-postgres audit-dependencies audit-browser admin-no-vite admin-bundle-scan admin-production-smoke admin-docker
