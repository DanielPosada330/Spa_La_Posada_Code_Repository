"""Generate Product Consumption reports from Zenoti for all centers.

Downloads consumption data for the last 30 days, enriches with product
metadata, and exports each center to its own CSV file in the output/ directory.

Usage:
    python -m zenoti_excel_automation.code_process.zenoti_report_generation
"""

from zenoti_excel_automation.code_process.utils import (
    load_config,
    download_consumption_report,
    get_center_products,
    enrich_with_pricing,
    export_to_csv,
)

config = load_config()

for center_id, center_name in config["centers"].items():
    if not center_id:
        print(f"{center_name}: no GUID set in config.env, skipping")
        continue

    stock_data = download_consumption_report(config, center_id, center_name)
    if not stock_data:
        continue

    products_lookup = get_center_products(config, center_id, center_name)
    enriched = enrich_with_pricing(stock_data, products_lookup)
    filename = f"consumption_{center_name}.csv"
    export_to_csv(enriched, filename)
