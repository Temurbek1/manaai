"""Loopback-only single-chat lab; default simulation, optional paid-model factory.

Run: .venv/bin/uvicorn scripts.mana_chat_lab:create_app --factory --host 127.0.0.1 --port 8092
The separate create_live_app factory uses configured models, fictional sources
and the same durable 2000-token limits. Neither factory can send push or grants.
"""

import ipaddress
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.api.routes import mana_child_safety, mana_conversion, mana_family_agents
from app.api.security import require_backend_bearer_token
from app.core.openapi import OPENAPI_TAGS
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.core.validation_errors import sanitized_request_validation_handler
from app.mana_ai.domain.family_collection import FamilyCollectionWindow
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget
from app.services.lab_collection import LabCollectionClock
from app.services.mana_chat_lab import (
    LAB_CHILD,
    LAB_PARENT,
    ChatLab,
    LabBootstrap,
    LabOptions,
    LabState,
)


class LabCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: Literal["900001"]
    hour: Literal[9, 15]


def create_app(*, options: LabOptions | None = None) -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    selected = options or LabOptions(root / "data/chat-lab/simulation")
    assets = root / "tools/chat-lab"
    lab = ChatLab(selected)
    cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    async def local_session(request: Request) -> None:
        if not secrets.compare_digest(request.cookies.get("mana_chat_lab", ""), cookie):
            raise HTTPException(401, detail={"code": "lab_session_required"})
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin != expected or not secrets.compare_digest(
                request.headers.get("x-lab-csrf", ""), csrf
            ):
                raise HTTPException(403, detail={"code": "lab_csrf_failed"})
            if request.url.path.endswith("/parent-touch/chat"):
                raise HTTPException(409, detail={"code": "lab_use_review_first_messages"})
            try:
                body = await request.json()
            except ValueError:
                raise HTTPException(422, detail={"code": "lab_json_required"}) from None
            if not isinstance(body, dict) or body.get("parent_id") != LAB_PARENT:
                raise HTTPException(403, detail={"code": "lab_family_not_allowed"})
            if body.get("child_id", LAB_CHILD) != LAB_CHILD:
                raise HTTPException(403, detail={"code": "lab_child_not_allowed"})
        parent = request.query_params.get("parent_id")
        if parent is not None and parent != LAB_PARENT:
            raise HTTPException(403, detail={"code": "lab_family_not_allowed"})

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await lab.start()
            app.state.parent_chat_service = lab.touch
            yield
        finally:
            await lab.close()

    app = FastAPI(
        title="MANA fictional chat lab",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_tags=OPENAPI_TAGS,
    )
    app.state.chat_lab = lab
    app.dependency_overrides[require_backend_bearer_token] = local_session
    app.add_exception_handler(RequestValidationError, sanitized_request_validation_handler)
    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=32768)

    @app.middleware("http")
    async def loopback_and_private(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            local = (
                request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
            )
        except ValueError:
            local = False
        if not local:
            return JSONResponse({"detail": {"code": "lab_loopback_only"}}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'self'"
                ),
            }
        )
        return response

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"], www_redirect=False
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def page() -> HTMLResponse:
        response = HTMLResponse((assets / "index.html").read_text().replace("__LAB_CSRF__", csrf))
        response.set_cookie("mana_chat_lab", cookie, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/lab-assets/{name}", include_in_schema=False)
    async def asset(name: Literal["lab.js", "lab.css"]) -> FileResponse:
        return FileResponse(assets / name)

    @app.get("/lab/bootstrap", response_model=LabBootstrap, dependencies=[Depends(local_session)])
    async def bootstrap() -> LabBootstrap:
        return lab.bootstrap()

    @app.get("/lab/state", response_model=LabState, dependencies=[Depends(local_session)])
    async def state() -> LabState:
        return await mana_family_agents.controlled(lab.state())

    @app.post(
        "/lab/child-battery",
        response_model=FamilySourceReceipt,
        dependencies=[Depends(local_session)],
    )
    async def child_battery(payload: FamilySourceTarget) -> FamilySourceReceipt:
        return await mana_family_agents.controlled(lab.sources.read_child_battery(payload))

    @app.post(
        "/lab/child-observation",
        response_model=FamilySourceReceipt,
        dependencies=[Depends(local_session)],
    )
    async def child_observation(payload: FamilySourceTarget) -> FamilySourceReceipt:
        return await mana_family_agents.controlled(lab.sources.read(payload))

    @app.post(
        "/lab/collection",
        response_model=FamilyCollectionWindow,
        dependencies=[Depends(local_session)],
    )
    async def collect(payload: LabCollectionRequest) -> FamilyCollectionWindow:
        if lab.collection is None:
            raise HTTPException(409, detail={"code": "lab_collection_disabled"})
        return await mana_family_agents.controlled(lab.collection.collect(payload.hour))

    @app.post(
        "/lab/retention-scenario",
        dependencies=[Depends(local_session)],
        response_model=dict[str, str],
    )
    async def retention_scenario() -> dict[str, str]:
        return await mana_family_agents.controlled(lab.prepare_retention_scenario())

    for router in (mana_family_agents.router, mana_child_safety.router, mana_conversion.router):
        app.include_router(router, prefix="/api/v1/mana-ai")
    return app


def create_live_app() -> FastAPI:
    """Explicit paid inference opt-in; no live family/data/write adapter is enabled."""
    root = Path(__file__).resolve().parents[1]
    return create_app(options=LabOptions(root / "data/chat-lab/real-model", real_model=True))


def create_native_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(root / "data/chat-lab/native-simulation", native_sources=True)
    )


def create_native_live_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/native-real-model", real_model=True, native_sources=True
        )
    )


def create_observation_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/observation-simulation",
            native_sources=True,
            native_observations=True,
        )
    )


def create_observation_live_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/observation-real-model",
            real_model=True,
            native_sources=True,
            native_observations=True,
        )
    )


def create_collection_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/collection-simulation",
            native_sources=True,
            native_observations=True,
            scheduled_collection=True,
            clock=LabCollectionClock(),
        )
    )


def create_source_review_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/source-review-simulation",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
        )
    )


def create_source_review_live_app() -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/source-review-real-model",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            real_model=True,
        )
    )


def create_reminder_app() -> FastAPI:
    """Fictional reminder chat, real wall clock, no paid/provider/write adapters."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/reminder-simulation",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
        )
    )


def create_reminder_live_app() -> FastAPI:
    """Separate explicit paid opt-in; only the single fictional family is exposed."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/reminder-real-model",
            real_model=True,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
        )
    )


def create_retention_app() -> FastAPI:
    """One fictional family, actual wall clock and SQL; no push, live data or paid model."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/retention-simulation",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
        )
    )


def create_retention_live_app() -> FastAPI:
    """Explicit paid model only; fictional data and real clock, no live parent contacts."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/retention-real-model",
            real_model=True,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
        )
    )


def create_upsell_app() -> FastAPI:
    """Fictional catalog and family; no payments, push, grants or live source adapters."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/upsell-simulation",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
        )
    )


def create_upsell_live_app() -> FastAPI:
    """Explicit paid inference, still fictional family/catalog and no financial action."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/upsell-real-model",
            real_model=True,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
        )
    )


def create_profile_app() -> FastAPI:
    """Fictional current tariff in the same single-chat lab, without live providers."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/profile-simulation",
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
            tariff_context=True,
        )
    )


def create_profile_live_app() -> FastAPI:
    """Explicit paid inference with fictional account facts; no live source or write."""
    root = Path(__file__).resolve().parents[1]
    return create_app(
        options=LabOptions(
            root / "data/chat-lab/profile-real-model",
            real_model=True,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
            tariff_context=True,
        )
    )
