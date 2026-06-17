"""
Thin wrapper around the backend API for the Streamlit dashboard.

Every function returns (data, error) - error is None on success, or a
human-readable string on failure. Keeps page code free of try/except
boilerplate and lets pages show a friendly "backend not reachable" message
instead of crashing.
"""

import os

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TIMEOUT = 30  # file uploads / OCR can be slower than typical API calls


def _request(method: str, path: str, **kwargs):
    url = f"{API_BASE_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        return None, f"Could not reach backend at {API_BASE_URL}: {exc}"

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return None, f"{resp.status_code}: {detail}"

    if resp.status_code == 204 or not resp.content:
        return None, None

    try:
        return resp.json(), None
    except ValueError:
        return None, "Backend returned a non-JSON response."


def get(path: str, params: dict | None = None):
    return _request("GET", path, params=params)


def post(path: str, params: dict | None = None, json_body: dict | None = None, files=None, data=None):
    return _request("POST", path, params=params, json=json_body, files=files, data=data)


def patch(path: str, json_body: dict | None = None):
    return _request("PATCH", path, json=json_body)


def file_url(path: str) -> str:
    """Build a direct URL for an endpoint that returns a binary file
    (used for embedding/downloading rather than fetching via requests)."""
    return f"{API_BASE_URL}{path}"
