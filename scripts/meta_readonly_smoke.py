import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.services.meta_marketing_client import MetaMarketingClient


async def run(max_accounts: int, lookback_days: int) -> None:
    settings = get_settings()
    if settings.meta_real_writes_enabled:
        raise SystemExit("Refusing smoke test while META_REAL_WRITES_ENABLED is true")
    if not settings.is_meta_configured:
        raise SystemExit("META_ACCESS_TOKEN is not configured")

    client = MetaMarketingClient(settings)
    accounts = await client.fetch_configured_ad_accounts()
    totals = {"campaigns": 0, "ad_sets": 0, "ads": 0, "insights": 0}
    today = datetime.now(UTC).date()
    since = today - timedelta(days=lookback_days)
    for account in accounts[:max_accounts]:
        account_id = account.get("id")
        if not isinstance(account_id, str):
            continue
        campaigns, ad_sets, ads, insights = await asyncio.gather(
            client.fetch_campaigns(account_id),
            client.fetch_adsets(account_id),
            client.fetch_ads(account_id),
            client.fetch_insights(
                account_id=account_id,
                level="ad",
                date_start=since,
                date_stop=today,
                time_increment=1,
                attribution_windows=settings.meta_action_attribution_windows,
            ),
        )
        totals["campaigns"] += len(campaigns)
        totals["ad_sets"] += len(ad_sets)
        totals["ads"] += len(ads)
        totals["insights"] += len(insights)

    diagnostics = client.consume_diagnostics()
    print(
        json.dumps(
            {
                "mode": "read_only",
                "graph_api_version": client.api_version,
                "accessible_accounts": len(accounts),
                "accounts_checked": min(len(accounts), max_accounts),
                "totals": totals,
                "request_count": len(diagnostics),
                "rate_limit_observed": any(item.rate_limit_observed for item in diagnostics),
            },
            sort_keys=True,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an explicit, bounded, GET-only Meta Marketing API smoke test.",
    )
    parser.add_argument("--confirm-read-only", action="store_true")
    parser.add_argument("--max-accounts", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--lookback-days", type=int, default=7, choices=range(1, 31))
    arguments = parser.parse_args()
    if not arguments.confirm_read_only:
        parser.error("--confirm-read-only is required")
    asyncio.run(run(arguments.max_accounts, arguments.lookback_days))


if __name__ == "__main__":
    main()
