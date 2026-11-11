"""A11 transport-only Make POST. Never equate HTTP 200 with processing ACK.

No PostgreSQL or CRM operations in this module; one HTTPS POST, no redirects,
no retries. Caller must separately journal its dispatch reservation.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request, build_opener

from crm_quality.make_orchestration import (
    MakeSafetyError, NoRedirect, canonical, validate_hook, validate_payload,
)


class TransportUnconfirmed(MakeSafetyError):
    """Transport may or may not have been accepted; must not retry blindly."""


@dataclass(frozen=True)
class AcceptedUnverified:
    event_id: str
    http_status: int = 200
    processing_acknowledged: bool = False


def post_once_accepted_only(url: str, apikey: str, payload: dict, *, opener=None) -> AcceptedUnverified:
    """Return an unverified transport receipt; no delivery/processing claim.

    Unknown responses, timeouts, redirects or errors must be treated as
    ambiguous after caller has reserved the event. No automatic retry.
    """
    validate_hook(url, apikey)
    validate_payload(payload)
    req = Request(
        url, data=canonical(payload).encode('utf-8'), method='POST', headers={
            'Content-Type': 'application/json',
            'Accept': 'text/plain',
            'x-make-apikey': apikey,
            'User-Agent': 'crm-quality-a11-async/1.0',
        }
    )
    transport = opener if opener is not None else build_opener(NoRedirect())
    with transport.open(req, timeout=15) as response:
        status = response.status
        data = response.read(1025)
    if status != 200 or len(data) > 1024 or data.strip() != b'Accepted':
        raise TransportUnconfirmed('Unexpected Make transport reply; delivery NOT verified')
    return AcceptedUnverified(payload['event_id'])
