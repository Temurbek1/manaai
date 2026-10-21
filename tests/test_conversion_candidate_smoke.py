from scripts.mana_conversion_smoke import main


async def test_conversion_hermetic_packaged_lifecycle() -> None:
    summary = await main()
    assert summary["schema"] == 9
    assert summary["real_contacts"] == 0
