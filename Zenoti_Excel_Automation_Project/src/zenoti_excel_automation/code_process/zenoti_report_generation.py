"""Generate Product Consumption reports from Zenoti for all centers.

Downloads consumption data for the last 30 days, enriches with product
metadata, and exports each center to its own CSV file in the output/ directory.

Usage:
    python -m zenoti_excel_automation.code_process.zenoti_report_generation
"""

import logging

from zenoti_excel_automation.code_process.utils import (
    download_consumption_report,
    enrich_with_pricing,
    export_to_csv,
    get_center_products,
    load_config,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Generate consumption reports for all configured centers."""
    config = load_config()

    for center_id, center_name in config["centers"].items():
        if not center_id:
            logger.warning(f"{center_name}: no GUID set in config.env, skipping")
            continue

        stock_data = download_consumption_report(config, center_id, center_name)
        if not stock_data:
            continue

        products_lookup = get_center_products(config, center_id, center_name)
        enriched = enrich_with_pricing(stock_data, products_lookup)
        filename = f"product_consumption_report_{center_name}.csv"
        export_to_csv(enriched, filename)


if __name__ == "__main__":
    main()
