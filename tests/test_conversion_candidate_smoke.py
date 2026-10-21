from scripts.mana_conversion_smoke import main


async def test_conversion_hermetic_packaged_lifecycle() -> None:
    summary = await main()
    assert summary["schema"] == 9
    assert summary["real_contacts"] == 0


async def test_account_verified_hermetic_packaged_lifecycle() -> None:
    summary = await main(verify_accounts=True)
    assert summary["schema"] == 10
    assert summary["mocked_account_reads"] == 4
    assert summary["source_unknown_preserved"] is True
    assert summary["source_auth_refusal_preserved"] is True
    assert summary["real_contacts"] == 0
