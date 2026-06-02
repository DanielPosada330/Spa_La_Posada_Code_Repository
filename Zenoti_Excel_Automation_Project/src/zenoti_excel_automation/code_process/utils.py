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

import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import polars as pl
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_ENV_API_KEY = "ZENOTI_API_KEY"
_ENV_APPLICATION_ID = "ZENOTI_APPLICATION_ID"
_ENV_SECRET_ID = "ZENOTI_SECRET_ID"
_ENV_ACCOUNT_NAME = "ZENOTI_ACCOUNT_NAME"
_ENV_USER_NAME = "ZENOTI_USER_NAME"
_ENV_PASSWORD = "ZENOTI_PASSWORD"
_ENV_API_BASE_URL = "ZENOTI_API_BASE_URL"
_ENV_DEVICE_ID = "ZENOTI_DEVICE_ID"
_ENV_CENTER_ID_BROWNSVILLE = "ZENOTI_CENTER_ID_BROWNSVILLE"
_ENV_CENTER_ID_MCALLEN = "ZENOTI_CENTER_ID_MCALLEN"
_ENV_CENTER_ID_HARLINGEN = "ZENOTI_CENTER_ID_HARLINGEN"
_ENV_OUTPUT_DIR = "ZENOTI_OUTPUT_DIR"
_ENV_REQUEST_TIMEOUT = "ZENOTI_REQUEST_TIMEOUT"

_DEFAULT_API_BASE_URL = "https://api.zenoti.com/v1"
_DEFAULT_DEVICE_ID = "zenoti-automation"

_HTTP_OK = 200
_HTTP_CONTENT_TYPE = "Content-Type"
_HTTP_ACCEPT = "accept"
_HTTP_AUTHORIZATION = "Authorization"
_HTTP_APPLICATION_JSON = "application/json"

_API_TOKENS = "/tokens"
API_ENDPOINT_CENTERS = "/centers"
API_ENDPOINT_STOCK_MOVEMENT = "/inventory/stock_movement"
_API_CENTER_PRODUCTS = "/centers/{center_id}/products"

_AUTH_BEARER_PREFIX = "bearer "
_AUTH_APIKEY_PREFIX = "apikey "

_JSON_CREDENTIALS = "credentials"
_JSON_ACCESS_TOKEN = "access_token"
_JSON_LIST = "list"
_JSON_PRODUCTS = "products"
_JSON_PAGE_INFO = "page_info"
_JSON_TOTAL = "total"
_JSON_CODE = "code"
_JSON_NAME = "name"
_JSON_RETAIL = "retail"
_JSON_CONSUMMABLE = "consummable"
_JSON_CATEGORY_NAME = "category_name"
_JSON_SUBCATEGORY_NAME = "subcategory_name"
_JSON_UNIT = "unit"
_JSON_COMMISSION = "commission"
_JSON_QUANTITY = "quantity"
_JSON_PRODUCT_CODE = "product_code"
_JSON_ELIGIBLE = "eligible"
_JSON_GRANT_TYPE = "grant_type"
_JSON_PASSWORD = "password"
_JSON_APP_ID = "app_id"
_JSON_APP_SECRET = "app_secret"
_JSON_DEVICE_ID = "device_id"
_JSON_ACCOUNT_NAME = "account_name"
_JSON_USER_NAME = "user_name"

_CACHE_ACCESS_TOKEN = "_access_token"

DATE_FORMAT = "%Y-%m-%d"

_CENTER_BROWNSVILLE = "Brownsville"
_CENTER_MCALLEN = "McAllen"
_CENTER_HARLINGEN = "Harlingen"

_CENTER_DISPLAY_NAMES: dict[str, str] = {
    _ENV_CENTER_ID_BROWNSVILLE: _CENTER_BROWNSVILLE,
    _ENV_CENTER_ID_MCALLEN: _CENTER_MCALLEN,
    _ENV_CENTER_ID_HARLINGEN: _CENTER_HARLINGEN,
}

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "assets" / "config.env"


class ReportType(Enum):
    """Report type values for consumption reports."""

    ALL = 1
    RETAIL = 3


_EMPTY_DATA_ERROR = "No data to export."


def load_config(config_path: Path | str | None = None) -> dict:
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
        "api_key": os.getenv(_ENV_API_KEY),
        "application_id": os.getenv(_ENV_APPLICATION_ID),
        "secret_id": os.getenv(_ENV_SECRET_ID),
        "account_name": os.getenv(_ENV_ACCOUNT_NAME),
        "user_name": os.getenv(_ENV_USER_NAME),
        "password": os.getenv(_ENV_PASSWORD),
        "api_base_url": os.getenv(_ENV_API_BASE_URL, _DEFAULT_API_BASE_URL),
        "device_id": os.getenv(_ENV_DEVICE_ID, _DEFAULT_DEVICE_ID),
        "output_dir": os.getenv(_ENV_OUTPUT_DIR, "output"),
        "request_timeout": int(os.getenv(_ENV_REQUEST_TIMEOUT, "30")),
        "centers": {
            os.getenv(env_var): display_name
            for env_var, display_name in _CENTER_DISPLAY_NAMES.items()
        },
    }


def generate_token(config: dict) -> str | None:
    """Request an OAuth bearer token from the Zenoti API.

    Sends a POST to ``/v1/tokens`` with the account credentials and app
    ID/secret stored in *config*.  The token is used by
    :func:`get_auth_headers` to authorize subsequent API calls.

    Args:
        config: Dict returned by :func:`load_config`.

    Returns:
        str: The ``access_token`` string on success.

        None: If the request fails (an error message is logged).

    """
    url = f"{config['api_base_url']}{_API_TOKENS}"
    payload = {
        _JSON_ACCOUNT_NAME: config[_JSON_ACCOUNT_NAME],
        _JSON_USER_NAME: config[_JSON_USER_NAME],
        _JSON_PASSWORD: config[_JSON_PASSWORD],
        _JSON_GRANT_TYPE: _JSON_PASSWORD,
        _JSON_APP_ID: config["application_id"],
        _JSON_APP_SECRET: config["secret_id"],
        _JSON_DEVICE_ID: config[_JSON_DEVICE_ID],
    }
    headers = {
        _HTTP_ACCEPT: _HTTP_APPLICATION_JSON,
        _HTTP_CONTENT_TYPE: _HTTP_APPLICATION_JSON,
    }
    timeout = config.get("request_timeout", 30)
    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code == _HTTP_OK:
        return response.json()[_JSON_CREDENTIALS][_JSON_ACCESS_TOKEN]
    logger.error("Failed to generate token. Status: %s", response.status_code)
    logger.error("Response: %s", response.text)
    return None


def get_auth_headers(config: dict) -> dict:
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
    token = config.get(_CACHE_ACCESS_TOKEN) or generate_token(config)
    if token:
        config[_CACHE_ACCESS_TOKEN] = token
        return {
            _HTTP_ACCEPT: _HTTP_APPLICATION_JSON,
            _HTTP_AUTHORIZATION: f"{_AUTH_BEARER_PREFIX}{token}",
        }
    return {
        _HTTP_ACCEPT: _HTTP_APPLICATION_JSON,
        _HTTP_AUTHORIZATION: f"{_AUTH_APIKEY_PREFIX}{config['api_key']}",
    }


def call_zenoti_api(
    config: dict, endpoint: str, params: dict | None = None
) -> dict | None:
    """Send an authenticated GET request to a Zenoti API endpoint.

    Args:
        config: Dict returned by :func:`load_config`.
        endpoint: API path relative to the base URL,
            e.g. ``"/centers"`` or ``"/inventory/stock_movement"``.
        params: Optional dict of query parameters.

    Returns:
        dict: Parsed JSON response on success (HTTP 200).

        None: If the request fails (an error message is logged).

    """
    url = f"{config['api_base_url']}{endpoint}"
    headers = get_auth_headers(config)
    timeout = config.get("request_timeout", 30)
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    if response.status_code == _HTTP_OK:
        return response.json()
    logger.error("API call failed. Status: %s", response.status_code)
    logger.error("Response: %s", response.text)
    return None


def download_consumption_report(
    config: dict,
    center_id: str,
    center_name: str,
    days: int = 30,
    report_type: ReportType | int = ReportType.RETAIL,
) -> list[dict]:
    """Download stock movement (consumption) data for a center.

    Fetches the Zenoti stock movement report for the last *days* days and
    returns the product-level consumption records as a list of dicts.

    See :class:`ReportType` for available report type values.

    Args:
        config: Dict returned by :func:`load_config`.
        center_id: GUID of the center to query.
        center_name: Human-readable center name (used in log messages).
        days: Number of days back from today for the report window.
        report_type: Zenoti report type (default ``ReportType.RETAIL``).

    Returns:
        list[dict]: Stock movement records, or an empty list on failure.

    """
    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    params = {
        "center_id": center_id,
        "start_date": start_date.strftime(DATE_FORMAT),
        "end_date": end_date.strftime(DATE_FORMAT),
        "report_type": report_type.value
        if isinstance(report_type, ReportType)
        else report_type,
    }
    result = call_zenoti_api(config, API_ENDPOINT_STOCK_MOVEMENT, params=params)
    if result is None:
        logger.error("%s: failed to download consumption report.", center_name)
        return []
    items = result.get(_JSON_LIST, [])
    logger.info("%s: %d consumption records retrieved.", center_name, len(items))
    return items


def get_center_products(
    config: dict, center_id: str, center_name: str
) -> dict[str, dict]:
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
            _API_CENTER_PRODUCTS.format(center_id=center_id),
            params={"page": page, "size": 100},
        )
        if result is None:
            logger.error("%s: failed to fetch products page %d.", center_name, page)
            break
        products = result.get(_JSON_PRODUCTS, [])
        all_products.extend(products)
        total = result.get(_JSON_PAGE_INFO, {}).get(_JSON_TOTAL, 0)
        if not products or len(all_products) >= total:
            break
        page += 1

    logger.info("%s: %d products fetched.", center_name, len(all_products))
    lookup = {}
    for p in all_products:
        quantity = p.get(_JSON_QUANTITY) or {}
        unit_str = quantity.get(_JSON_UNIT, "")
        lookup[p[_JSON_CODE]] = {
            _JSON_NAME: p.get(_JSON_NAME, ""),
            _JSON_RETAIL: p.get(_JSON_RETAIL, False),
            _JSON_CONSUMMABLE: p.get(_JSON_CONSUMMABLE, False),
            _JSON_CATEGORY_NAME: p.get(_JSON_CATEGORY_NAME, ""),
            _JSON_SUBCATEGORY_NAME: p.get(_JSON_SUBCATEGORY_NAME, ""),
            _JSON_UNIT: unit_str,
            _JSON_COMMISSION: p.get(_JSON_COMMISSION),
        }
    return lookup


def enrich_with_pricing(
    stock_data: list[dict], products_lookup: dict[str, dict]
) -> list[dict]:
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
        code = item.get(_JSON_PRODUCT_CODE, "")
        meta = products_lookup.get(code, {})
        enriched.append(
            {
                **item,
                "is_retail": meta.get(_JSON_RETAIL, False),
                "is_consummable": meta.get(_JSON_CONSUMMABLE, False),
                "product_category": meta.get(_JSON_CATEGORY_NAME, ""),
                "product_subcategory": meta.get(_JSON_SUBCATEGORY_NAME, ""),
                "product_unit": meta.get(_JSON_UNIT, ""),
                "commission_eligible": (meta.get(_JSON_COMMISSION) or {}).get(
                    _JSON_ELIGIBLE, False
                ),
            }
        )
    return enriched


def export_to_csv(
    data: list[dict], filename: str, output_dir: str | None = None
) -> Path:
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
        raise ValueError(_EMPTY_DATA_ERROR)
    if output_dir is None:
        output_dir = os.getenv(_ENV_OUTPUT_DIR, "output")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    filepath = out_path / filename
    df = pl.DataFrame(data)
    df.write_csv(filepath)
    logger.info("Exported %d rows to %s", len(data), filepath)
    return filepath
