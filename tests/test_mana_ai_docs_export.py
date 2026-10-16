import json
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.mana_ai.domain.enums import ManaAICapability
from scripts import export_mana_ai_docs


def test_public_docs_export_has_only_product_contracts(monkeypatch: MonkeyPatch) -> None:
    def deny_settings(*args: object, **kwargs: object) -> None:
        raise AssertionError("Documentation export must not load deployment secrets")

    get_settings.cache_clear()
    monkeypatch.setattr(Settings, "__init__", deny_settings)
    schema = export_mana_ai_docs.build_schema()
    expected = {f"/api/v1/mana-ai/{item.value.replace('_', '-')}" for item in ManaAICapability}
    assert set(schema["paths"]) == expected | {
        "/api/v1/mana-ai/capabilities",
        "/api/v1/mana-ai/chat",
    }
    assert len(schema["paths"]) == 13
    assert schema["servers"] == [{"url": "/", "description": "Same-origin production API"}]
    assert set(schema["components"]["securitySchemes"]) == {"BearerToken", "ParentChatBackendToken"}
    for path, operations in schema["paths"].items():
        operation = operations["get" if path.endswith("/capabilities") else "post"]
        scheme = "ParentChatBackendToken" if path.endswith("/chat") else "BearerToken"
        assert operation["security"] == [{scheme: []}]
        if path.endswith("/chat"):
            assert operations["get"]["security"] == [{scheme: []}]
        if "post" in operations:
            assert operations["post"]["requestBody"]["content"]["application/json"]["examples"]


def test_html_uses_local_assets_without_authorization_persistence() -> None:
    html = export_mana_ai_docs.build_html().decode()
    assert '<meta charset="utf-8">' in html
    assert '<script charset="utf-8"' in html
    assert "/docs-assets/swagger-ui-bundle.js" in html
    assert "/docs-assets/swagger-ui.css" in html
    assert '"persistAuthorization": false' in html
    assert '"validatorUrl": null' in html
    assert '"tryItOutEnabled": false' in html
    assert "jsdelivr" not in html


def test_export_is_exclusive_and_records_runtime(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "docs"
    image = "sha256:" + "a" * 64
    monkeypatch.setattr(
        sys, "argv", ["export", "--output-dir", str(output), "--runtime-image", image]
    )
    export_mana_ai_docs.main()
    assert "5.33.2-aaaaaaaaaaaa-utf8" in (output / "index.html").read_text()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest == {
        "runtime_image": image,
        "path_count": 13,
        "swagger_ui_version": "5.33.2",
        "source_reads": 0,
        "provider_calls": 0,
    }
    with pytest.raises(FileExistsError):
        export_mana_ai_docs.main()


def test_asset_revision_cannot_inject_html() -> None:
    with pytest.raises(ValueError):
        export_mana_ai_docs.build_html('" onclick="unsafe')


def test_invalid_image_ref_is_refused(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "docs"
    monkeypatch.setattr(
        sys, "argv", ["export", "--output-dir", str(output), "--runtime-image", "latest"]
    )
    with pytest.raises(SystemExit):
        export_mana_ai_docs.main()
    assert not output.exists()
