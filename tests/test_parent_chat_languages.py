import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.application.parent_languages import neutral_parent_reply, parent_language
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ResponseLanguage
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_child_safety_store import store
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, message
from tests.test_parent_chat_adapters import model_payload, settings
from tests.test_parent_touch_evidence import TouchModel


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Привет. Помоги ребёнку наладить сон.", "ru"),
        ("Обычно ложится в 22:00.", "ru"),
        ("Спасибо.", "ru"),
        ("Salom. Farzandimning uyqu tartibini yaxshilashga yordam bering.", "uz-Latn"),
        ("Maktab uchun soat 7:00 da turadi.", "uz-Latn"),
        ("Farzandingiz soat nechada uxlaydi?", "uz-Latn"),
        ("Rahmat.", "uz-Latn"),
        ("Салом. Фарзандим мактабга боради.", "uz-Cyrl"),
        ("What time does your child go to sleep?", "en"),
        ("Hello, please help my child. Rahmat.", "en"),
        ("Salom, yordam bering, please.", "uz-Latn"),
        ("7:00", None),
        ("Ha", None),
        ("Hola, quiero hablar contigo.", None),
        ("你好，我有一个问题。", None),
        ("Synthetic", None),
    ],
)
def test_conservative_presentation_hints(text: str, expected: ResponseLanguage | None) -> None:
    assert parent_language(text) == expected


async def test_neutral_reply_inherits_private_frozen_language_not_other_families(
    tmp_path: Path,
) -> None:
    repository, model = await store(tmp_path / "language.db"), TouchModel()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=Children(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    original = message(text="Salom. Farzandimning uyqu tartibi haqida gaplashamiz.")

    def last_language() -> ResponseLanguage | None:
        return model.prompts[-1].response_language

    saved = await touch.send(original)
    assert last_language() == "uz-Latn"
    for text in ("Ha", "7:00"):
        await touch.send(message(text=text))
        assert last_language() == "uz-Latn"
    await touch.send(message(text="Привет. Помоги ребёнку со сном."))
    assert last_language() == "ru"
    assert await touch.send(original) == saved  # Old language/receipt, no new generation.
    assert model.calls == 4
    with repository._connect() as connection:
        reference = connection.execute(
            "SELECT language_reference FROM family_turn_metadata WHERE parent_id='123' "
            "ORDER BY turn_id LIMIT 1"
        ).fetchone()[0]
        assert reference == original.message
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parent_chat_turns WHERE parent_id='123' AND message='7:00'"
            ).fetchone()[0]
            == 1
        )
    await touch.send(message(parent_id="456", text="7:00"))
    assert last_language() is None
    await touch.send(message(text="你好，我有一个问题。"))
    assert last_language() is None
    assert not neutral_parent_reply("你好，我有一个问题。")


@pytest.mark.parametrize(
    ("question", "valid"),
    [
        ("Farzandingiz soat nechada uxlaydi?", True),
        ("What time does your child go to sleep?", False),
    ],
)
async def test_english_specialist_copy_is_withheld_with_verified_usage(
    tmp_path: Path, question: str, valid: bool
) -> None:
    repository = await store(tmp_path / "sdk.db")
    selected = (await repository.enqueue(intent(), NOW)).question
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": "Rahmat.",
            "question": question,
            "notice_communicated": False,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        receipt = await adapter.respond(
            ChatPrompt(
                "Synthetic",
                (),
                structured_reply=True,
                slot_reply=True,
                question=selected,
                response_language="uz-Latn",
            ),
            max_output_tokens=512,
        )
    assert receipt.usage.total == 150 and receipt.completed == valid
    assert receipt.question_id == (selected.question_id if valid else None)
    assert receipt.failure_code == (None if valid else "reply_language_mismatch")
