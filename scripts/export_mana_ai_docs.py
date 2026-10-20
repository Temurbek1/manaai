"""Export public product contracts without starting providers, workers or a database."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

from app.api.routes.mana_ai import router
from app.api.routes.mana_ai_chat import router as parent_chat_router
from app.api.routes.mana_family_agents import router as family_agents_router
from app.api.security import require_bearer_token
from app.core.openapi import SWAGGER_UI_PARAMETERS

SWAGGER_UI_VERSION = "5.33.2"


def build_schema() -> dict[str, Any]:
    app = FastAPI(
        title="MANA AI",
        version="0.1.0",
        description=(
            "Product inference and optional persistent parent chat. "
            "Send application evidence and receive a typed analysis. "
            "Authorize inference with APP_API_KEY. The isolated parent chat uses its "
            "separate MANA backend token; never distribute it to mobile clients. "
            "Proposed actions are not executed. "
            "Executing an analysis uses the configured paid model."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(
        router,
        prefix="/api/v1/mana-ai",
        tags=["mana-ai"],
        dependencies=[Depends(require_bearer_token)],
    )
    app.include_router(parent_chat_router, prefix="/api/v1/mana-ai", tags=["mana-ai"])
    app.include_router(family_agents_router, prefix="/api/v1/mana-ai", tags=["mana-ai"])
    schema = app.openapi()
    schema["servers"] = [{"url": "/", "description": "Same-origin production API"}]
    return schema


def build_html(asset_revision: str | None = None) -> bytes:
    if asset_revision is not None and not re.fullmatch(r"[a-f0-9]{12}", asset_revision):
        raise ValueError("Asset revision must be a twelve-character image digest")
    asset_version = SWAGGER_UI_VERSION + (f"-{asset_revision}" if asset_revision else "")
    html = bytes(
        get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="MANA AI — Swagger",
            swagger_js_url=f"/docs-assets/swagger-ui-bundle.js?v={asset_version}-utf8",
            swagger_css_url=f"/docs-assets/swagger-ui.css?v={asset_version}-utf8",
            swagger_favicon_url="data:,",
            swagger_ui_parameters={
                **SWAGGER_UI_PARAMETERS,
                "validatorUrl": None,
                "tryItOutEnabled": False,
            },
        ).body
    )
    return html.replace(b"<head>", b'<head>\n    <meta charset="utf-8">', 1).replace(
        b'<script src="/docs-assets/', b'<script charset="utf-8" src="/docs-assets/', 1
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-image", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.runtime_image):
        parser.error("runtime-image must be an immutable sha256 image identifier")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    schema = build_schema()
    (args.output_dir / "openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "index.html").write_bytes(build_html(args.runtime_image[7:19]))
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "runtime_image": args.runtime_image,
                "path_count": len(schema["paths"]),
                "swagger_ui_version": SWAGGER_UI_VERSION,
                "source_reads": 0,
                "provider_calls": 0,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
