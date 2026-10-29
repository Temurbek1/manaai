from pathlib import Path

from pydantic import SecretStr
from pytest import MonkeyPatch

from app.core.config import Settings
from app.services import parent_chat_runtime as runtime_module
from tests.test_child_safety_store import limits
from tests.test_parent_chat import Children
from tests.test_parent_chat_api import BACKEND_TOKEN
from tests.test_parent_touch_evidence import TouchModel


async def test_role_model_settings_are_independent_and_never_replace_legacy_inference(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str]] = []

    class Model(TouchModel):
        async def close(self) -> None:
            pass

    def touch_model(settings: Settings) -> Model:
        seen.append(("touch", settings.openai_model))
        return Model()

    def safety_model(settings: Settings) -> Model:
        seen.append(("safety", settings.openai_model))
        return Model()

    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", touch_model)
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", safety_model)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: Children())
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("fake-key"),
        openai_model="shared-inference-model",
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_chat_database_path=tmp_path / "active.db",
        mana_parent_touch_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_limits=limits(
            server_daily_tokens=5000, parent_daily_tokens=4000, job_tokens=2000
        ),
        mana_parent_touch_model="touch-only-model",
        mana_child_safety_model="safety-only-model",
        manakids_api_username="fake-user",
        manakids_api_password=SecretStr("fake-password"),
    )
    async with runtime_module.parent_chat_runtime(config) as service:
        assert service
    assert seen == [("touch", "touch-only-model"), ("safety", "safety-only-model")]
    assert config.openai_model == "shared-inference-model"
    legacy = config.model_copy(
        update={
            "mana_parent_touch_enabled": False,
            "mana_child_safety_enabled": False,
            "mana_parent_chat_database_path": tmp_path / "legacy.db",
        }
    )
    async with runtime_module.parent_chat_runtime(legacy) as service:
        assert service
    assert seen[-1] == ("touch", "shared-inference-model") and len(seen) == 3


def test_family_quality_defaults_are_inactive_and_do_not_replace_the_existing_model() -> None:
    config = Settings(_env_file=None, openai_api_key=SecretStr("fake-key"))
    assert config.mana_parent_touch_model == "gpt-5.4"
    assert config.mana_child_safety_model == "gpt-5.4-mini"
    assert not config.mana_parent_touch_enabled and not config.mana_child_safety_enabled
    assert config.openai_model == "gpt-5.4-nano"
    assert config.mana_parent_chat_daily_tokens == 5000
