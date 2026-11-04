"""HubSpot developer test account connectivity probe (GET-only).

Reads at most two Contacts and two Companies, printing counts/status only.
No CRM values are saved or printed, and no write endpoints are invoked.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.hubapi.com"
FIELDS = {
    "contacts": "firstname,lastname",
    "companies": "name,domain",
}


def load_key() -> str:
    key = os.environ.get("HUBSPOT_SERVICE_KEY", "").strip()
    if key:
        return key
    file = ROOT / ".env"
    if not file.exists():
        return ""
    for raw_line in file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "HUBSPOT_SERVICE_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def check_object(object_type: str, fields: str, key: str) -> bool:
    params = urlencode({"limit": 2, "properties": fields})
    url = f"{API_BASE}/crm/objects/2026-03/{object_type}?{params}"
    request = Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "crm-data-quality-readonly-check/0.1",
    }, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            status = response.status
            body = json.load(response)
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            print(f"{object_type}: unexpected JSON format")
            return False
        count = len(body["results"])
        has_more = bool(body.get("paging", {}).get("next"))
        print(f"{object_type}: HTTP {status} | returned={count} | has_next_page={has_more}")
        return True
    except HTTPError as exc:
        # Intentionally do not print response bodies, headers, or credentials.
        print(f"{object_type}: HTTP {exc.code} | check key scopes and API access")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"{object_type}: network or response error ({type(exc).__name__})")
    return False


def main() -> int:
    key = load_key()
    if not key or key == "PASTE_YOUR_KEY_HERE":
        print("Missing HUBSPOT_SERVICE_KEY in local .env or environment")
        return 2
    print("M1 HubSpot GET-only connectivity check (max 2 records per object)")
    results = [check_object(kind, fields, key) for kind, fields in FIELDS.items()]
    if all(results):
        print("PASS: contacts and companies both readable; no writes attempted")
        return 0
    print("FAIL: one or more API reads failed; no writes attempted")
    return 1


if __name__ == "__main__":
    sys.exit(main())
