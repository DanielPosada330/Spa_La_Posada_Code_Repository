"""Utility functions for the Zenoti Excel Automation project.

This module handles:
  - Loading API credentials and center IDs from config.env
  - Generating OAuth bearer tokens for authenticated requests
  - Building authorization headers (bearer token with apikey fallback)
  - Making GET requests to Zenoti API endpoints
  - Downloading consumption (stock movement) reports per center
  - Fetching product metadata and enriching reports
  - Exporting enriched data to CSV via Polars

Typical usage:

    config = load_config()
    for center_id, center_name in config["centers"].items():
        stock = download_consumption_report(config, center_id, center_name)
        products = get_center_products(config, center_id, center_name)
        enriched = enrich_with_pricing(stock, products)
        export_to_csv(enriched, f"consumption_{center_name}.csv")

Refer to config.env for required credentials and center GUIDs.
"""

import os
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import requests
from dotenv import load_dotenv


_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "config.env"
)


def load_config(config_path=None):
    """Load Zenoti API credentials and center IDs from a .env file.

    Reads the environment file at *config_path* (defaults to
    ``assets/config.env`` relative to this module's parent directory) and
    returns a dict with everything needed to authenticate and call the
    Zenoti API.

    Args:
        config_path: Path to the .env file. Defaults to
            ``assets/config.env`` next to the package root.

    Returns:
        dict: Configuration with the following keys:

            - **api_key** - Zenoti API key for fallback auth
            - **application_id** - OAuth app ID
            - **secret_id** - OAuth app secret
            - **account_name** - Zenoti account name
            - **user_name** - Employee username
            - **password** - Employee password
            - **api_base_url** - API base URL
            - **device_id** - Device identifier for token requests
            - **centers** - Dict mapping center GUIDs to display names
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    load_dotenv(dotenv_path=config_path)

    return {
        "api_key": os.getenv("ZENOTI_API_KEY"),
        "application_id": os.getenv("ZENOTI_APPLICATION_ID"),
        "secret_id": os.getenv("ZENOTI_SECRET_ID"),
        "account_name": os.getenv("ZENOTI_ACCOUNT_NAME"),
        "user_name": os.getenv("ZENOTI_USER_NAME"),
        "password": os.getenv("ZENOTI_PASSWORD"),
        "api_base_url": os.getenv(
            "ZENOTI_API_BASE_URL", "https://api.zenoti.com/v1"
        ),
        "device_id": os.getenv("ZENOTI_DEVICE_ID", "zenoti-automation"),
        "centers": {
            os.getenv("ZENOTI_CENTER_ID_BROWNSVILLE"): "Brownsville",
            os.getenv("ZENOTI_CENTER_ID_MCALLEN"): "McAllen",
            os.getenv("ZENOTI_CENTER_ID_HARLINGEN"): "Harlingen",
        },
    }


def generate_token(config):
    """Request an OAuth bearer token from the Zenoti API.

    Sends a POST to ``/v1/tokens`` with the account credentials and app
    ID/secret stored in *config*.  The token is used by
    :func:`get_auth_headers` to authorize subsequent API calls.

    Args:
        config: Dict returned by :func:`load_config`.

    Returns:
        str: The ``access_token`` string on success.

        None: If the request fails (an error message is printed).
    """
    url = f"{config['api_base_url']}/tokens"
    payload = {
        "account_name": config["account_name"],
        "user_name": config["user_name"],
        "password": config["password"],
        "grant_type": "password",
        "app_id": config["application_id"],
        "app_secret": config["secret_id"],
        "device_id": config["device_id"],
    }
    headers = {"accept": "application/json", "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()["credentials"]["access_token"]
    print(f"Failed to generate token. Status: {response.status_code}")
    print(f"Response: {response.text}")
    return None


def get_auth_headers(config):
    """Build authorization headers for Zenoti API requests.

    Generates a bearer token on the first call and caches it in the
    *config* dict under the ``_access_token`` key for reuse on
    subsequent calls.  This avoids requesting a new token for every
    API request in a session.

    Falls back to API-key auth if token generation fails.

    Args:
        config: Dict returned by :func:`load_config`.

    Returns:
        dict: Headers dict with ``accept`` and ``Authorization`` keys.
    """
    token = config.get("_access_token") or generate_token(config)
    if token:
        config["_access_token"] = token
        return {"accept": "application/json", "Authorization": f"bearer {token}"}
    return {
        "accept": "application/json",
        "Authorization": f"apikey {config['api_key']}",
    }


def call_zenoti_api(config, endpoint, params=None):
    """Send an authenticated GET request to a Zenoti API endpoint.

    Args:
        config: Dict returned by :func:`load_config`.
        endpoint: API path relative to the base URL,
            e.g. ``"/centers"`` or ``"/inventory/stock_movement"``.
        params: Optional dict of query parameters.

    Returns:
        dict: Parsed JSON response on success (HTTP 200).

        None: If the request fails (an error message is printed).
    """
    url = f"{config['api_base_url']}{endpoint}"
    headers = get_auth_headers(config)
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    print(f"API call failed. Status: {response.status_code}")
    print(f"Response: {response.text}")
    return None


def download_consumption_report(config, center_id, center_name, days=30, report_type=3):
    """Download stock movement (consumption) data for a center.

    Fetches the Zenoti stock movement report for the last *days* days and
    returns the product-level consumption records as a list of dicts.

    report_type values:
        1 - All products (includes Miscellaneous / Tags categories)
        3 - Retail products only (excludes Miscellaneous / Tags)

    Args:
        config: Dict returned by :func:`load_config`.
        center_id: GUID of the center to query.
        center_name: Human-readable center name (used in log messages).
        days: Number of days back from today for the report window.
        report_type: Zenoti report type integer (default 3 = retail).

    Returns:
        list[dict]: Stock movement records, or an empty list on failure.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    params = {
        "center_id": center_id,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "report_type": report_type,
    }
    result = call_zenoti_api(config, "/inventory/stock_movement", params=params)
    if result is None:
        print(f"{center_name}: failed to download consumption report.")
        return []
    items = result.get("list", [])
    print(f"{center_name}: {len(items)} consumption records retrieved.")
    return items


def get_center_products(config, center_id, center_name):
    """Fetch all products for a center, handling pagination.

    The Zenoti products endpoint caps pages at 100 items regardless of the
    requested size.  This function iterates through all pages to collect
    every product and returns a lookup dict keyed by ``product_code``.

    Args:
        config: Dict returned by :func:`load_config`.
        center_id: GUID of the center to query.
        center_name: Human-readable center name (used in log messages).

    Returns:
        dict[str, dict]: Mapping from product code to product metadata.
            Each value contains at least ``name``, ``retail`` (bool),
            ``consummable`` (bool), ``category_name``, ``subcategory_name``,
            ``unit`` (str), and ``commission`` (dict or None).
    """
    all_products = []
    page = 1
    while True:
        result = call_zenoti_api(
            config,
            f"/centers/{center_id}/products",
            params={"page": page, "size": 100},
        )
        if result is None:
            print(f"{center_name}: failed to fetch products page {page}.")
            break
        products = result.get("products", [])
        all_products.extend(products)
        total = result.get("page_info", {}).get("total", 0)
        if not products or len(all_products) >= total:
            break
        page += 1

    print(f"{center_name}: {len(all_products)} products fetched.")
    lookup = {}
    for p in all_products:
        quantity = p.get("quantity") or {}
        unit_str = quantity.get("unit", "")
        lookup[p["code"]] = {
            "name": p.get("name", ""),
            "retail": p.get("retail", False),
            "consummable": p.get("consummable", False),
            "category_name": p.get("category_name", ""),
            "subcategory_name": p.get("subcategory_name", ""),
            "unit": unit_str,
            "commission": p.get("commission"),
        }
    return lookup


def enrich_with_pricing(stock_data, products_lookup):
    """Enrich stock movement records with product metadata.

    Joins each stock movement record with its corresponding product metadata
    (retail flag, consummable flag, category, subcategory, unit) using the
    ``product_code`` field as the join key.

    Args:
        stock_data: List of dicts from :func:`download_consumption_report`.
        products_lookup: Dict from :func:`get_center_products`, keyed by
            product code.

    Returns:
        list[dict]: The input records with added product metadata fields.
    """
    enriched = []
    for item in stock_data:
        code = item.get("product_code", "")
        meta = products_lookup.get(code, {})
        enriched.append(
            {
                **item,
                "is_retail": meta.get("retail", False),
                "is_consummable": meta.get("consummable", False),
                "product_category": meta.get("category_name", ""),
                "product_subcategory": meta.get("subcategory_name", ""),
                "product_unit": meta.get("unit", ""),
                "commission_eligible": (meta.get("commission") or {}).get(
                    "eligible", False
                ),
            }
        )
    return enriched


def export_to_csv(data, filename, output_dir="output"):
    """Export a list of dicts to a CSV file using Polars.

    Creates *output_dir* if it does not exist.

    Args:
        data: List of dicts (e.g., from :func:`enrich_with_pricing`).
        filename: Name of the CSV file, e.g. ``"consumption_Brownsville.csv"``.
        output_dir: Directory to write the file into (default ``"output"``).

    Returns:
        pathlib.Path: The path to the written CSV file.

    Raises:
        ValueError: If *data* is empty.
    """
    if not data:
        raise ValueError("No data to export.")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    filepath = out_path / filename
    df = pl.DataFrame(data)
    df.write_csv(filepath)
    print(f"Exported {len(data)} rows to {filepath}")
    return filepath