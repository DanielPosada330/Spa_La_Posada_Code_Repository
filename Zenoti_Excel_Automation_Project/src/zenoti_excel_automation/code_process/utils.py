"""Utility functions for connecting to the Zenoti API and loading configuration.

This module handles:
  - Loading API credentials and center IDs from config.env
  - Generating OAuth bearer tokens for authenticated requests
  - Building authorization headers (bearer token with apikey fallback)
  - Making GET requests to Zenoti API endpoints

Typical usage:

    config = load_config()
    result = call_zenoti_api(config, "/centers")
    for center in result["centers"]:
        print(center["name"])

Refer to config.env for required credentials and center GUIDs.
"""

import os
from pathlib import Path

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

    Attempts bearer-token auth first by calling :func:`generate_token`.
    Falls back to API-key auth if token generation fails.

    Args:
        config: Dict returned by :func:`load_config`.

    Returns:
        dict: Headers dict with ``accept`` and ``Authorization`` keys.
    """
    token = generate_token(config)
    if token:
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