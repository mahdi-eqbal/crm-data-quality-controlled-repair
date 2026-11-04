"""M1b: read-only HubSpot account/Contact->Company association probe.

NO CRM writes, NO local database writes, and NO PII printed.
Requires existing scripts/m1_snapshot_hubspot.py and local .env from M1a.
"""
from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from m1_snapshot_hubspot import collect, local_env

EXPECTED_PORTAL_ID = "149703596"
ACCOUNT_DETAILS = "https://api.hubapi.com/account-info/2026-03/details"
ASSOCIATION_BASE = "https://api.hubapi.com/crm/v4/objects/contacts"
MAX_ASSOC_PAGES = 10


def get_json(url: str, token: str) -> dict:
    """GET JSON with bounded retries. Never echo request URL, response, or secrets."""
    req = Request(url, method="GET", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "crm-quality-m1b-readonly/0.1",
    })
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as resp:
                payload = json.load(resp)
            if not isinstance(payload, dict):
                raise ValueError("Unexpected JSON shape")
            return payload
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("Retries exhausted")


def verify_account(token: str, expected: str = EXPECTED_PORTAL_ID) -> str:
    """Return VERIFIED or UNVERIFIED. Mismatches are fatal."""
    try:
        details = get_json(ACCOUNT_DETAILS, token)
    except HTTPError as exc:
        if exc.code in (401, 403, 404):
            print(f"ACCOUNT: UNVERIFIED (account-info GET HTTP {exc.code}; no scopes changed)")
            return "UNVERIFIED"
        raise
    actual = details.get("portalId")
    if actual is None:
        print("ACCOUNT: UNVERIFIED (portalId absent in API response)")
        return "UNVERIFIED"
    if str(actual) != expected:
        raise ValueError("HubSpot portal ID does NOT match dedicated test account; stopped")
    print(f"ACCOUNT: VERIFIED | portalId={actual}")
    return "VERIFIED"


def get_association_count(contact_id: str, token: str) -> int:
    """Count unique associated company IDs with per-record cursor pagination."""
    ids: set[str] = set()
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_ASSOC_PAGES):
        query = {"limit": "500"}
        if cursor:
            query["after"] = cursor
        url = (f"{ASSOCIATION_BASE}/{quote(str(contact_id), safe='')}"
               f"/associations/companies?{urlencode(query)}")
        result = get_json(url, token)
        rows = result.get("results")
        if not isinstance(rows, list):
            raise ValueError("Association response must include results list")
        for item in rows:
            if not isinstance(item, dict) or item.get("toObjectId") is None:
                raise ValueError("Association response missing company ID")
            ids.add(str(item["toObjectId"]))
        cursor = ((result.get("paging") or {}).get("next") or {}).get("after")
        if not cursor:
            return len(ids)
        if cursor in seen_cursors:
            raise ValueError("Repeated associations pagination cursor")
        seen_cursors.add(cursor)
        time.sleep(0.15)
    raise ValueError("Association pagination safety cap reached")


def main() -> int:
    env = local_env()
    token = env.get("HUBSPOT_SERVICE_KEY", "").strip()
    if not token or token == "PASTE_YOUR_KEY_HERE":
        print("FAIL: Missing HUBSPOT_SERVICE_KEY in local .env")
        return 2
    if env.get("HUBSPOT_ACCOUNT_ID") != EXPECTED_PORTAL_ID:
        print("FAIL: HUBSPOT_ACCOUNT_ID is not the dedicated test account; stopped")
        return 2

    print("M1b HubSpot read-only association probe (GET only; no DB writes)")
    try:
        identity = verify_account(token)
        contacts = collect("contacts", token)  # already has a safety cap in M1a
        counts = [get_association_count(item["id"], token) for item in contacts]
    except HTTPError as exc:
        print(f"FAIL: HubSpot API HTTP {exc.code}; no writes attempted")
        return 1
    except (URLError, OSError, TimeoutError):
        print("FAIL: network error; no writes attempted")
        return 1
    except (ValueError, RuntimeError) as exc:
        print(f"FAIL: {type(exc).__name__}; {str(exc)}")
        return 1

    print(f"ASSOCIATIONS: contacts_checked={len(contacts)} | "
          f"unique_contact_company_links={sum(counts)} | "
          f"contacts_without_company={sum(c == 0 for c in counts)}")
    print("PASS: read-only association probe completed; no CRM/DB changes")
    if identity != "VERIFIED":
        print("NOTE: account identity is NOT independently verified; use the HubSpot UI to confirm the Service Key belongs to test portal 149703596.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
