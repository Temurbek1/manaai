"""Offline collection calculator: no settings, credentials, sources or scheduler."""

import argparse
import json
from decimal import Decimal, InvalidOperation

from app.mana_ai.domain.family_collection_cost import family_collection_forecast


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parents", type=int, required=True)
    parser.add_argument("--connected-links", type=int, required=True)
    parser.add_argument("--include-app-usage", action="store_true")
    parser.add_argument("--firestore-usd-per-100000-reads", required=True)
    args = parser.parse_args()
    try:
        result = family_collection_forecast(
            parents=args.parents,
            connected_links=args.connected_links,
            include_app_usage=args.include_app_usage,
            read_price_per_100000=Decimal(args.firestore_usd_per_100000_reads),
        )
    except (ValueError, InvalidOperation) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
