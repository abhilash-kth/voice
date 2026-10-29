"""Server-side VoiceLink reseller API client.

Only the backend talks to VoiceLink. The reseller token/password, provider
client ids and SIP credentials never reach a browser. Response handling is
defensive: VoiceLink wraps payloads as ``{"status": true, "data": ...}``,
redirects are never followed with credentials attached, and raw KYC/OTP
error bodies are never echoed back. For KYC validation failures we expose
only allowlisted field messages after redacting anything that looks like a
submitted identity value.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Optional

from . import telephony_settings

logger = logging.getLogger("voice-agent-saas-voicelink")

_login_token: str = ""
_login_token_for: str = ""
_login_lock = asyncio.Lock()


class VoiceLinkError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502,
                 uncertain: bool = False):
        super().__init__(message)
        self.status_code = status_code
        # True when a mutating request may have been applied provider-side
        # (timeout / 5xx). Callers must reconcile by reading, never replay.
        self.uncertain = uncertain


async def configured() -> bool:
    return (await telephony_settings.get_settings()).configured


def reset_auth_cache() -> None:
    global _login_token, _login_token_for
    _login_token = ""
    _login_token_for = ""


def _auth_fingerprint(settings) -> str:
    raw = "\0".join((
        settings.voicelink_api_base_url,
        settings.static_token,
        settings.voicelink_username,
        settings.voicelink_password,
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _login(settings) -> str:
    global _login_token, _login_token_for
    fingerprint = _auth_fingerprint(settings)
    async with _login_lock:
        if _login_token and _login_token_for == fingerprint:
            return _login_token
        import httpx
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as c:
                r = await c.post(
                    f"{settings.voicelink_api_base_url}/auth/login",
                    json={"username": settings.voicelink_username,
                          "password": settings.voicelink_password},
                    headers={"Accept": "application/json"})
        except Exception as e:
            raise VoiceLinkError(f"VoiceLink login unreachable: {type(e).__name__}",
                                 503, uncertain=True) from None
        payload = _json_or_none(r)
        data = payload.get("data") if isinstance(payload, dict) else None
        token = ""
        if isinstance(data, dict):
            token = str(data.get("access_token") or data.get("token")
                        or data.get("plain_api_token") or "")
        if r.status_code >= 400 or not token:
            raise VoiceLinkError(
                "VoiceLink login failed. Check the API token or "
                "username/password in Super Admin -> Telephony -> Settings.",
                503)
        _login_token = token
        _login_token_for = fingerprint
        return token


def _json_or_none(resp) -> Any:
    try:
        return resp.json() if resp.content else None
    except Exception:
        return None


def _provider_message(payload: Any) -> str:
    if isinstance(payload, dict):
        msg = payload.get("message") or payload.get("error")
        if isinstance(msg, str) and msg.strip():
            return re.sub(r"\s+", " ", msg).strip()[:300]
        errors = payload.get("errors")
        if isinstance(errors, dict) and errors:
            first = next(iter(errors.values()))
            if isinstance(first, list) and first:
                return str(first[0])[:300]
            return str(first)[:300]
    return ""


_KYC_FIELD_LABELS = {
    "client_id": "Phone account",
    "term_and_condition": "Terms acceptance",
    "account_type": "Account type",
    "full_name": "Full legal name",
    "business_name": "Business name",
    "email": "Email",
    "phone": "Contact number",
    "billing_address": "Billing address",
    "state": "State",
    "city": "City",
    "pincode": "Postal code",
    "pan_number": "PAN",
    "pan_holder_name": "PAN holder name",
    "gst_number": "GSTIN",
    "document": "Document",
    "document_type": "Document type",
    "redirect_url": "Verification return URL",
    "username": "Email account",
    "otp": "Email code",
    # VoiceLink's current portal KYC can also gate final submission on these
    # provider-side prerequisites. Labels only name the missing step; the
    # provider's message text is still redacted below.
    "email_verified": "Email verification",
    "is_email_verified": "Email verification",
    "email_verification": "Email verification",
    "live_photo": "Live photo",
    "live_photo_verified": "Live photo",
    "photo": "Live photo",
    "photo_verified": "Live photo",
    "kyc_photo": "Live photo",
    "profile_photo": "Live photo",
    "selfie": "Live photo",
    "signature": "Signature",
    "digital_signature": "Signature",
    "signature_image": "Signature",
    "agreement": "Agreement",
    "agreement_accepted": "Agreement",
    "agreement_reacceptance_required": "Agreement",
    "terms_accepted": "Terms acceptance",
    "latitude": "Location",
    "longitude": "Location",
    "location": "Location",
    "geo_location": "Location",
    "current_step": "Verification step",
    "step": "Verification step",
    "steps": "Verification steps",
    "kyc_status": "Verification status",
    "status": "Verification status",
    "is_complete": "Verification completion",
    "documents": "Supporting documents",
    "pan_document": "PAN document",
    "aadhaar_document": "Aadhaar document",
    "gst_document": "GST document",
    "address_proof": "Address proof",
    "identity_proof": "Identity proof",
    "kyc": "Verification",
    "final_submit": "Final submission",
}


def _redact_provider_text(raw: str) -> str:
    msg = re.sub(r"\s+", " ", raw).strip()
    msg = re.sub(r"(['\"]).*?\1", "[redacted]", msg)
    msg = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", msg)
    msg = re.sub(r"https?://\S+", "[redacted]", msg)
    msg = re.sub(
        r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b",
        "[redacted]", msg, flags=re.IGNORECASE)
    msg = re.sub(
        r"\b[A-Z]{5}\d{4}[A-Z]\b", "[redacted]", msg,
        flags=re.IGNORECASE)
    msg = re.sub(r"\+?\d[\d ()-]{7,}\d", "[redacted]", msg)
    msg = re.sub(r"\b[A-Za-z0-9_-]{24,}\b", "[redacted]", msg)
    return msg.strip()[:180]


def _safe_top_level_reason(payload: dict) -> str:
    """Classify a provider business-rule message without echoing its text.

    Final-submit and email-OTP failures often have only a top-level
    ``message`` (for example, a still-missing live photo or an already
    verified email), rather than Laravel's field ``errors`` object. We map
    only recognizable prerequisite keywords to our own wording, so no raw
    provider text—and therefore no echoed identity/account value—is logged
    or returned.
    """
    texts: list[str] = []
    containers = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
    elif isinstance(data, str):
        texts.append(data)
    for item in containers:
        for key in ("message", "error", "detail"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    text = " ".join(texts).lower()
    if not text:
        return ""
    if "already" in text and ("verif" in text or "confirm" in text):
        return ("Email verification: VoiceLink reports that this email is "
                "already verified or no new code is needed.")
    if "otp" in text and "expired" in text:
        return "Email code: The code has expired; request a new one."
    if "otp" in text and ("invalid" in text or "incorrect" in text):
        return "Email code: The code is invalid."
    if "too many" in text or "try again after" in text or "wait" in text:
        return "Email code: Wait before requesting another code."
    if ("user not found" in text or "account not found" in text
            or "username" in text and ("not found" in text
                                        or "does not exist" in text)):
        return ("Email account: VoiceLink could not find the managed "
                "account for email confirmation.")
    if ("live photo" in text or "selfie" in text or "photo capture" in text
            or "kyc photo" in text or "profile photo" in text):
        return ("Live photo: VoiceLink still requires its live-photo "
                "verification step.")
    if "signature" in text:
        return ("Signature: VoiceLink still requires its signature step.")
    if "agreement" in text or ("terms" in text and "accept" in text):
        return ("Agreement: VoiceLink still requires agreement/terms "
                "acceptance.")
    if "latitude" in text or "longitude" in text or "location" in text:
        return ("Location: VoiceLink still requires its location step.")
    if "email" in text and ("verif" in text or "confirm" in text):
        return ("Email verification: VoiceLink still requires the managed "
                "account email to be verified.")
    if "gst" in text:
        return "GSTIN: VoiceLink still requires GST verification or its document."
    if "pan" in text:
        return "PAN: VoiceLink still requires PAN verification or its document."
    if "aadhaar" in text or "aadhar" in text:
        return ("Aadhaar: VoiceLink still requires Aadhaar verification or "
                "its document.")
    if "document" in text:
        return "Supporting documents: VoiceLink reports a document is still required."
    if "client_id" in text or "client id" in text:
        return ("Final submission: VoiceLink did not accept the "
                "client-scoped final submission.")
    if ("complete all" in text or "incomplete" in text
            or "pending" in text and "step" in text):
        return ("Verification steps: VoiceLink reports that one or more "
                "required steps are still incomplete.")
    return ""


def _safe_error_shape(payload: Any) -> str:
    """Return response key/field names only, never any response values."""
    def keys(value: Any) -> list[str]:
        if not isinstance(value, dict):
            return []
        return [str(k) for k in value
                if re.fullmatch(r"[A-Za-z0-9_-]{1,50}", str(k))][:15]

    if not isinstance(payload, dict):
        return f"payload_type={type(payload).__name__}"
    data = payload.get("data")
    errors = payload.get("errors")
    if not isinstance(errors, (dict, list)) and isinstance(data, dict):
        errors = data.get("errors")
    fields = keys(errors)
    if isinstance(errors, list):
        fields = [str(item.get("field") or item.get("key") or "")
                  for item in errors if isinstance(item, dict)]
        fields = [f for f in fields
                  if re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", f)][:15]
    return (f"keys={keys(payload)} data_type={type(data).__name__} "
            f"data_keys={keys(data)} error_fields={fields}")


def _safe_validation_message(payload: Any) -> str:
    """Return up to three sanitized KYC/OTP validation details.

    VoiceLink/Laravel normally returns field names plus rule text such as
    "The full name field is required." We expose only allowlisted field
    messages after redacting anything that looks like a submitted identity
    value. If there is no usable field error, a keyword-classified
    prerequisite (live photo, email verification, and similar) may be
    returned in our own wording; the raw provider message is never echoed.
    """
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if not isinstance(errors, (dict, list)):
        data = payload.get("data")
        errors = data.get("errors") if isinstance(data, dict) else None

    details: list[str] = []

    def add(label: str, raw: Any) -> None:
        if len(details) >= 3:
            return
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        if isinstance(raw, dict):
            raw = raw.get("message") or raw.get("error") or ""
        if not isinstance(raw, str) or not raw.strip():
            return
        msg = _redact_provider_text(raw)
        if msg:
            details.append(f"{label}: {msg}")

    if isinstance(errors, dict):
        for field, raw in errors.items():
            label = _KYC_FIELD_LABELS.get(str(field).split(".", 1)[0])
            if label:
                add(label, raw)
            if len(details) == 3:
                break
    elif isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                field = str(item.get("field") or item.get("key") or "")
                label = _KYC_FIELD_LABELS.get(field.split(".", 1)[0])
                if label:
                    add(label, item.get("message") or item.get("error"))
            elif isinstance(item, str):
                # A bare string has no trustworthy field name; classify it
                # like a top-level business message rather than echoing it.
                reason = _safe_top_level_reason({"message": item})
                if reason and reason not in details:
                    details.append(reason)
            if len(details) == 3:
                break

    if details:
        return "; ".join(details)
    return _safe_top_level_reason(payload)


async def request(method: str, path: str, *, json: Any = None,
                  params: Optional[dict] = None, data: Optional[dict] = None,
                  files: Optional[dict] = None, _retried: bool = False) -> Any:
    global _login_token, _login_token_for
    if not path.startswith("/"):
        raise VoiceLinkError("Invalid VoiceLink path", 500)
    settings = await telephony_settings.get_settings()
    if not settings.configured:
        raise VoiceLinkError(
            "VoiceLink is not configured. Add the API token or "
            "username/password in Super Admin -> Telephony -> Settings.",
            503)
    token = settings.static_token or await _login(settings)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as c:
            resp = await c.request(
                method, f"{settings.voicelink_api_base_url}{path}",
                json=json, params=params, data=data, files=files,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"})
    except Exception as e:
        raise VoiceLinkError(
            f"VoiceLink request failed ({type(e).__name__}). "
            "Check provider connectivity before retrying.",
            503, uncertain=(method.upper() != "GET")) from None
    if 300 <= resp.status_code < 400:
        raise VoiceLinkError("VoiceLink redirected the API request; refusing "
                             "to follow it with credentials.", 502,
                             uncertain=(method.upper() != "GET"))
    payload = _json_or_none(resp)
    if resp.status_code == 401 and not settings.static_token and not _retried:
        if _login_token_for == _auth_fingerprint(settings):
            _login_token = ""
            _login_token_for = ""
        return await request(method, path, json=json, params=params,
                             data=data, files=files, _retried=True)
    sensitive = ("kyc" in path) or ("otp" in path)
    if resp.status_code >= 400:
        if sensitive:
            detail = _safe_validation_message(payload)
            if detail:
                logger.warning(
                    "VoiceLink verification validation failed: path=%s %s",
                    path, detail)
                msg = (f"VoiceLink rejected the verification request "
                       f"(HTTP {resp.status_code}): {detail}")
            else:
                logger.warning(
                    "VoiceLink verification rejection shape: path=%s "
                    "http_status=%s %s",
                    path, resp.status_code, _safe_error_shape(payload))
                msg = (f"VoiceLink rejected the verification request "
                       f"(HTTP {resp.status_code}). Check the details and "
                       "try again.")
        else:
            msg = _provider_message(payload) or f"VoiceLink HTTP {resp.status_code}"
        raise VoiceLinkError(msg, resp.status_code,
                             uncertain=(resp.status_code >= 500
                                        and method.upper() != "GET"))
    if isinstance(payload, dict) and payload.get("status") is False:
        if sensitive:
            detail = _safe_validation_message(payload)
            if detail:
                logger.warning(
                    "VoiceLink verification validation failed: path=%s %s",
                    path, detail)
            else:
                logger.warning(
                    "VoiceLink verification rejection shape: path=%s "
                    "provider_status=false %s",
                    path, _safe_error_shape(payload))
            msg = (f"VoiceLink rejected the verification request: {detail}"
                   if detail else
                   "VoiceLink rejected the verification request.")
        else:
            msg = _provider_message(payload) or "VoiceLink rejected the request."
        raise VoiceLinkError(msg, 400)
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


# ---------------------------------------------------------------------------
# Small shape helpers (provider responses vary between list/record wrappers)
# ---------------------------------------------------------------------------
def as_record(data: Any) -> dict:
    if isinstance(data, dict):
        inner = data.get("data")
        return inner if isinstance(inner, dict) else data
    return {}


def as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "clients", "dids", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def id_of(record: dict, *keys: str) -> str:
    for k in keys:
        v = record.get(k)
        if v is not None and str(v) != "":
            return str(v)
    return ""


def int_id(value: Any) -> Any:
    s = str(value or "")
    return int(s) if s.isdigit() else value


def money(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def normalize_in_number(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        digits = "91" + digits
    return f"+{digits}" if digits else ""


# ---------------------------------------------------------------------------
# Reseller / clients / wallet
# ---------------------------------------------------------------------------
async def profile() -> dict:
    return as_record(await request("GET", "/reseller/profile"))


async def clients() -> list[dict]:
    return [r for r in as_list(await request("GET", "/reseller/clients"))
            if isinstance(r, dict)]


async def create_client(payload: dict) -> dict:
    return as_record(await request("POST", "/reseller/client/create", json=payload))


async def update_client(client_id: str, payload: dict) -> dict:
    return as_record(await request(
        "POST", f"/reseller/client/update/{int_id(client_id)}", json=payload))


async def allocate_wallet(client_id: str, amount: float, description: str) -> Any:
    return await request(
        "POST", f"/reseller/client/allocate-wallet/{int_id(client_id)}",
        json={"amount": amount, "description": description or "Calling balance"})


# ---------------------------------------------------------------------------
# KYC (client-scoped; identity values pass through in memory only)
# ---------------------------------------------------------------------------
async def kyc_status(client_id: str) -> dict:
    return as_record(await request(
        "GET", "/reseller/kyc/status", params={"client_id": str(client_id)}))


async def kyc_step1(client_id: str, fields: dict) -> Any:
    return await request("POST", "/reseller/kyc/step-1-register-details",
                         json={"client_id": int_id(client_id), **fields})


async def kyc_step2_pan(client_id: str, pan_number: str, holder: str) -> Any:
    return await request("POST", "/reseller/kyc/step-2-pan-verify", json={
        "client_id": int_id(client_id), "pan_number": pan_number,
        "pan_holder_name": holder})


async def kyc_step3_aadhaar_init(client_id: str, redirect_url: str) -> dict:
    return as_record(await request("POST", "/reseller/kyc/step-3-aadhaar-init",
                                   json={"client_id": int_id(client_id),
                                         "redirect_url": redirect_url}))


async def kyc_step4_gst(client_id: str, gst_number: str) -> Any:
    return await request("POST", "/reseller/kyc/step-4-gst-verify", json={
        "client_id": int_id(client_id), "gst_number": gst_number})


async def kyc_final_submit(client_id: str) -> Any:
    return await request("POST", "/reseller/kyc/final-submit",
                         json={"client_id": int_id(client_id)})


async def kyc_upload_document(client_id: str, document_type: str, filename: str,
                              content: bytes, content_type: str) -> Any:
    return await request(
        "POST", "/reseller/kyc/upload-document",
        data={"client_id": str(client_id), "document_type": document_type},
        files={"document": (filename, content, content_type)})


async def verify_email_otp(username: str, otp: str) -> Any:
    return await request("POST", "/auth/verify-otp",
                         json={"username": username, "otp": otp})


async def resend_email_otp(username: str) -> Any:
    return await request("POST", "/auth/resend-otp", json={"username": username})


# ---------------------------------------------------------------------------
# DID purchase + assignment
# ---------------------------------------------------------------------------
async def search_dids(*, did_type: str, months: int, number: str = "",
                      page: int = 1, per_page: int = 25) -> Any:
    params = {"country_code": "+91", "type": str(did_type),
              "months": str(months), "page": str(page),
              "per_page": str(per_page)}
    if number:
        params["number"] = number
    return await request("GET", "/reseller/purchase/dids", params=params)


async def lock_did(did_id: str, months: int) -> dict:
    return as_record(await request("POST", "/reseller/purchase/lock-did",
                                   json={"did_ids": [int_id(did_id)],
                                         "months": months}))


async def add_channel(order_id: str, channel_count: int, months: int) -> Any:
    return await request("POST", "/reseller/purchase/add-channel", json={
        "order_id": int_id(order_id), "channel_count": channel_count,
        "months": months})


async def purchase_summary(order_id: str) -> dict:
    return as_record(await request(
        "GET", f"/reseller/purchase/summary/{int_id(order_id)}"))


async def confirm_purchase(order_id: str) -> dict:
    return as_record(await request("POST", "/reseller/purchase/confirm",
                                   json={"order_id": int_id(order_id)}))


async def map_did(client_id: str, did_id: str) -> dict:
    return as_record(await request("POST", "/reseller/client/map-did", json={
        "client_id": int_id(client_id), "did_id": int_id(did_id),
        "call_recording": 0, "user_status": 2}))


async def purchased_dids(client_id: str, page: int = 1) -> Any:
    return await request("GET", "/reseller/did/purchased", params={
        "client_id": str(client_id), "page": str(page), "per_page": "100"})


# ---------------------------------------------------------------------------
# SIP trunks + call routing (provider side of activation)
# ---------------------------------------------------------------------------
async def create_sip_trunk(payload: dict) -> dict:
    return as_record(await request("POST", "/sip-trunk/create", json=payload))


async def list_sip_trunks(client_id: Optional[str] = None) -> list[dict]:
    params = {"page": "1", "per_page": "100"}
    if client_id:
        params["client_id"] = str(client_id)
    data = await request("GET", "/sip-trunk/list", params=params)
    return [r for r in as_list(data) if isinstance(r, dict)]


async def update_sip_trunk(trunk_id: str, payload: dict) -> dict:
    return as_record(await request(
        "POST", f"/sip-trunk/update/{int_id(trunk_id)}", json=payload))


async def create_routing(payload: dict) -> dict:
    return as_record(await request("POST", "/call-routing/create", json=payload))


async def list_routing(client_id: str) -> list[dict]:
    data = await request("GET", "/call-routing/list",
                         params={"client_id": str(client_id)})
    return [r for r in as_list(data) if isinstance(r, dict)]


async def update_routing(routing_id: str, payload: dict) -> dict:
    return as_record(await request(
        "POST", f"/call-routing/update/{int_id(routing_id)}", json=payload))
