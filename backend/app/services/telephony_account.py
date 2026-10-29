"""VoiceLink account lifecycle for one SaaS customer: hidden provider
client creation/linking, sync, managed KYC, and calling-balance allocation.

Identity values (PAN/GST/OTP/documents) are forwarded to VoiceLink in
memory only. Only sanitized progress booleans are persisted.
"""
from __future__ import annotations

import re
import secrets
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from .. import repo
from . import telephony_settings
from . import voicelink_client as vl
from .telephony_policy import TelephonyError


# ---------------------------------------------------------------------------
# Provider profile / client row parsing (tolerant, secret-free)
# ---------------------------------------------------------------------------
def safe_profile(raw: dict) -> dict:
    wallet = raw.get("wallet") if isinstance(raw.get("wallet"), dict) else {}
    channels = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    plan = raw.get("active_plan") if isinstance(raw.get("active_plan"), dict) else {}
    rates = []
    for r in plan.get("did_type_rates") or []:
        if isinstance(r, dict):
            rates.append({
                "type_id": str(r.get("did_type_id") or r.get("id") or ""),
                "name": str(r.get("name") or "Phone number")[:80],
                "monthly_rate": vl.money(r.get("rate")),
            })
    return {
        "id": vl.id_of(raw, "id"),
        "active": raw.get("is_active") in (1, True, "1"),
        "verified": raw.get("is_verified") in (1, True, "1"),
        "billing_mode": str(raw.get("billing_mode") or ""),
        "currency": str(raw.get("currency") or wallet.get("currency") or ""),
        "wallet_balance": vl.money(wallet.get("balance", raw.get("wallet_balance"))),
        "channels_available": int(channels.get("available") or 0)
        if str(channels.get("available") or "").isdigit() else 0,
        "plan_name": str(plan.get("plan_name") or "")[:100],
        "plan_type": str(plan.get("plan_type") or ""),
        "pulse_seconds": plan.get("pulse_seconds")
        if isinstance(plan.get("pulse_seconds"), int) else None,
        "inbound_rate": vl.money(plan["inbound_rate"])
        if plan.get("inbound_rate") is not None else None,
        "outbound_rate": vl.money(plan["outbound_rate"])
        if plan.get("outbound_rate") is not None else None,
        "monthly_channel_rate": vl.money(plan.get("monthly_channel_rate")),
        "did_type_rates": rates,
    }


def _client_wallet(row: dict) -> float:
    if isinstance(row.get("wallet"), dict):
        return vl.money(row["wallet"].get("balance"))
    return vl.money(row.get("wallet_balance", row.get("balance")))


def _client_channels(row: dict) -> int:
    for key in ("channel_count", "channels_allocated", "channels"):
        v = row.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
        if isinstance(v, dict) and str(v.get("allocated") or "").isdigit():
            return int(v["allocated"])
    return 0


def _indian_phone_forms(phone: str = "") -> tuple[str, str]:
    """Return ``(VoiceLink digits, stored/display E.164)`` for an Indian mobile.

    Customers naturally enter ``+91XXXXXXXXXX``. VoiceLink's client-create
    validator is a digits-only rule (``digits_between``-style: it rejects the
    ``+`` with "The phone field must be between 7 and 15 digits"), so the
    provider payload must use ``91XXXXXXXXXX``. We keep ``+91...`` locally
    because the rest of the app displays/compares E.164 numbers. An empty
    optional setup phone stays empty; a supplied non-Indian number is
    rejected here with a clear message instead of VoiceLink's generic one.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return "", ""
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) != 12 or not digits.startswith("91"):
        raise TelephonyError(
            "Enter a 10-digit Indian mobile number, optionally with "
            "country code 91.", 400)
    return digits, f"+{digits}"


async def require_account(user_id: str) -> dict:
    account = await repo.get_account_by_user(user_id)
    if not account:
        raise TelephonyError(
            "Set up your phone account first (Phone Numbers page).", 409)
    if account["status"] == "suspended":
        raise TelephonyError("Your telephony account is suspended. "
                             "Contact support.", 403)
    return account


# ---------------------------------------------------------------------------
# Account setup + sync
# ---------------------------------------------------------------------------
async def setup_account(user_id: str, email: str, name: str = "",
                        phone: str = "") -> dict:
    existing = await repo.get_account_by_user(user_id)
    if existing:
        return await sync_account(existing)
    provider_phone, stored_phone = _indian_phone_forms(phone)
    # Channels selected with the monthly plan are the target allocation for
    # the new provider client. If the reseller pool cannot cover all of them
    # yet, start with what is available; a later DID quote buys the missing
    # provider channels inside that order.
    desired_channels = 1
    try:
        from . import subscription_service
        entitlement = await subscription_service.get_subscription(user_id)
        desired_channels = max(
            1, int(entitlement.get("plan_channels") or 1))
    except Exception:
        pass
    profile = safe_profile(await vl.profile())
    clients = await vl.clients()
    by_email = next(
        (c for c in clients
         if str(c.get("email") or "").lower() == email.lower()), None)
    if by_email is not None:
        client_id = vl.id_of(by_email, "id", "client_id")
        claimed = await repo.get_account_by_client(client_id)
        if claimed and claimed["user_id"] != user_id:
            raise TelephonyError(
                "This email is already linked to another workspace's phone "
                "account. Contact support.", 409)
        account = await repo.create_account(user_id, {
            "provider_reseller_id": profile["id"], "client_id": client_id,
            "username": str(by_email.get("username") or ""),
            "email": email, "name": name or email, "phone": stored_phone,
            "channels_allocated": _client_channels(by_email),
        })
        return await sync_account(account)

    if not profile["active"] or not profile["verified"]:
        raise TelephonyError(
            "The operator's VoiceLink reseller account needs verification "
            "before customer phone accounts can be created.", 409)
    if profile["billing_mode"] and profile["billing_mode"] != "prepaid":
        raise TelephonyError(
            "Managed phone setup requires prepaid reseller billing.", 409)
    if profile["channels_available"] < 1:
        raise TelephonyError(
            "No unallocated calling channel is available right now. "
            "Contact support.", 409)
    initial_channels = min(
        desired_channels, int(profile["channels_available"] or 1))

    settings = await telephony_settings.get_settings()
    display = (name or email.split("@")[0]).strip()
    parts = display.split()
    payload: dict[str, Any] = {
        "first_name": parts[0][:80],
        "last_name": (" ".join(parts[1:]) or "Customer")[:80],
        "email": email,
        "username": "vx_" + uuid.uuid4().hex[:24],
        # Sent only to VoiceLink; never stored or shown. Customers complete
        # KYC here and never need the provider portal password.
        "password": secrets.token_urlsafe(32),
        "is_active": 1, "channel_count": initial_channels,
        "negative_threshold": 0,
        "wallet_balance": 0,
        "wallet_bypass": int(settings.voicelink_wallet_bypass),
    }
    if provider_phone:
        payload["phone"] = provider_phone
    if profile["plan_type"] == "unlimited":
        payload["plan_type"] = "unlimited"
    else:
        if profile["pulse_seconds"]:
            payload["pulse_seconds"] = profile["pulse_seconds"]
        if profile["inbound_rate"] is not None:
            payload["inbound_rate"] = profile["inbound_rate"]
        if profile["outbound_rate"] is not None:
            payload["outbound_rate"] = profile["outbound_rate"]
    created = await vl.create_client(payload)
    client_id = vl.id_of(created, "client_id", "id")
    if not client_id:  # uncertain create: reconcile by email, never recreate
        again = next((c for c in await vl.clients()
                      if str(c.get("email") or "").lower() == email.lower()), None)
        client_id = vl.id_of(again or {}, "id", "client_id")
    if not client_id:
        raise TelephonyError(
            "VoiceLink did not return a client id. Press Set up again — it "
            "will link the created client by email instead of duplicating it.",
            502)
    account = await repo.create_account(user_id, {
        "provider_reseller_id": profile["id"], "client_id": client_id,
        "username": payload["username"], "email": email, "name": display,
        "phone": stored_phone, "channels_allocated": initial_channels,
    })
    return await sync_account(account)


async def sync_account(account: dict) -> dict:
    try:
        profile = safe_profile(await vl.profile())
    except Exception:
        profile = {"channels_available": account.get("channels_available") or 0,
                   "id": account.get("provider_reseller_id") or ""}
    row = next((c for c in await vl.clients()
                if vl.id_of(c, "id", "client_id") == str(account["client_id"])),
               None)
    if row is None:
        await repo.update_account(account["id"], {
            "status": "error",
            "last_error": "VoiceLink client no longer exists under the reseller.",
            "last_synced_at": repo._ts()})
        raise TelephonyError(
            "Your VoiceLink client could not be found. Contact support.", 409)
    provider_active = row.get("is_active") in (1, True, "1")
    status = account["status"]
    if not provider_active:
        status = "suspended"
    elif status in ("error", ""):
        status = "active"
    patch = {
        "provider_reseller_id": profile.get("id") or account.get("provider_reseller_id") or "",
        "username": str(row.get("username") or account.get("username") or ""),
        "wallet_balance": _client_wallet(row),
        "channels_allocated": _client_channels(row),
        "channels_available": profile.get("channels_available") or 0,
        "status": status, "last_error": "", "last_synced_at": repo._ts(),
    }
    account = await repo.update_account(account["id"], patch) or account
    try:
        await sync_kyc(account)
        account = await repo.get_account(account["id"]) or account
    except Exception as e:
        await repo.update_account(account["id"], {"last_error": str(e)[:500]})
    return await repo.get_account(account["id"]) or account


# ---------------------------------------------------------------------------
# KYC state + actions
# ---------------------------------------------------------------------------
def terms_url(raw_url: Optional[str] = None) -> str:
    if raw_url is None:
        raw_url = telephony_settings.env_fallback_settings().voicelink_kyc_terms_url
    raw = (raw_url or "").strip()
    if not raw:
        return ""
    try:
        u = urlparse(raw)
    except Exception:
        return ""
    if u.scheme != "https" or u.username or u.password or u.port:
        return ""
    if u.hostname not in ("app.voicelink.co.in", "voicelink.co.in"):
        return ""
    return raw


def kyc_state(raw: dict, settings=None) -> dict:
    effective = settings or telephony_settings.env_fallback_settings()
    account_type = raw.get("account_type")
    if account_type not in ("individual", "business"):
        account_type = "individual"
    business = account_type == "business"
    docs = raw.get("documents") if isinstance(raw.get("documents"), dict) else {}

    def doc(kind: str) -> dict:
        d = docs.get(kind) if isinstance(docs.get(kind), dict) else {}
        return {"verified": raw.get(f"{kind}_verified") is True,
                "uploaded": d.get("uploaded") is True}

    documents = {"pan": doc("pan"), "aadhaar": doc("aadhaar")}
    if business:
        documents["gst"] = doc("gst")
    verified = (
        raw.get("is_complete") is True and raw.get("kyc_status") == 1
        and raw.get("current_step") == "complete"
        and documents["pan"]["verified"] and documents["aadhaar"]["verified"]
        and (not business or documents["gst"]["verified"]))
    step = str(raw.get("current_step") or "register")
    if step not in ("register", "pan", "aadhaar", "gst", "complete"):
        step = "register"
    any_progress = any(d["verified"] or d["uploaded"]
                       for d in documents.values()) or step != "register"
    ready = raw.get("agreement_reacceptance_required") is not True and all(
        d["verified"] and d["uploaded"] for d in documents.values())
    if verified:
        status = "verified"
    elif ready or raw.get("is_complete") is True:
        status = "submitted"
    elif any_progress:
        status = "in_progress"
    else:
        status = "not_started"
    return {
        "status": status, "step": step, "account_type": account_type,
        "documents": documents, "ready_for_submission": ready,
        "agreement_needs_acceptance":
            raw.get("agreement_reacceptance_required") is True,
        "final_submission_available":
            bool(effective.kyc_finalize_verified),
        "terms_url": terms_url(effective.voicelink_kyc_terms_url),
    }


async def sync_kyc(account: dict) -> dict:
    settings = await telephony_settings.get_settings()
    state = kyc_state(await vl.kyc_status(account["client_id"]), settings)
    await repo.update_account(account["id"], {
        "kyc_status": state["status"], "kyc_step": state["step"],
        "kyc_meta": {k: state[k] for k in
                     ("step", "account_type", "documents",
                      "ready_for_submission", "agreement_needs_acceptance")},
        "last_synced_at": repo._ts(), "last_error": ""})
    return state


def _req(value: str, label: str) -> str:
    v = (value or "").strip()
    if not v:
        raise TelephonyError(f"{label} is required.", 400)
    return v


def validate_digilocker_redirect(value: Any, settings=None) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise TelephonyError("DigiLocker redirect is unavailable.", 503)
    effective = settings or telephony_settings.env_fallback_settings()
    u = urlparse(value)
    hosts = {"digilocker.gov.in", "digilocker.meripehchaan.gov.in"}
    hosts.update(effective.voicelink_kyc_redirect_hosts)
    if u.scheme != "https" or u.username or u.password or u.port \
            or (u.hostname or "") not in hosts:
        raise TelephonyError(
            "The identity-service redirect domain is not allowlisted. "
            "Ask the operator to add it in Super Admin -> Telephony -> "
            "Settings.", 503)
    return value


async def act_kyc(user_id: str, body, redirect_url: str) -> dict:
    settings = await telephony_settings.get_settings()
    account = await require_account(user_id)
    client_id = account["client_id"]
    action = body.action
    if action in ("verify_email", "resend_email"):
        username = account.get("username") or ""
        if not username:
            row = next((c for c in await vl.clients()
                        if vl.id_of(c, "id") == str(client_id)), None)
            username = str((row or {}).get("username") or "")
        if not username:
            raise TelephonyError(
                "Email confirmation needs operator review for this account.", 409)
        if action == "verify_email":
            if not re.fullmatch(r"\d{6}", body.otp or ""):
                raise TelephonyError("Enter the six-digit email code.", 400)
            await vl.verify_email_otp(username, body.otp)
        else:
            await vl.resend_email_otp(username)
        return {"kyc": await sync_kyc(account),
                "message": "Email confirmation updated."}
    if action == "register":
        if not body.accept_terms:
            raise TelephonyError(
                "Review and accept the verification terms to continue.", 400)
        if body.account_type not in ("individual", "business"):
            raise TelephonyError("Choose individual or business verification.", 400)
        phone = _req(body.phone, "Contact number")
        # Accept 10-digit, 91XXXXXXXXXX and +91XXXXXXXXXX input, but send
        # VoiceLink its digits-only provider format (see _indian_phone_forms).
        phone, _stored_phone = _indian_phone_forms(phone)
        if not re.fullmatch(r"\d{6}", body.pincode or ""):
            raise TelephonyError("Enter a six-digit postal code.", 400)
        fields = {
            "term_and_condition": True, "account_type": body.account_type,
            "full_name": _req(body.full_name, "Full legal name"),
            "phone": phone,
            "billing_address": _req(body.billing_address, "Billing address"),
            "state": _req(body.state, "State"), "city": _req(body.city, "City"),
            "pincode": body.pincode,
        }
        if body.account_type == "business":
            fields["business_name"] = _req(body.business_name, "Business name")
        await vl.kyc_step1(client_id, fields)
    elif action == "pan":
        pan = (body.pan_number or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan):
            raise TelephonyError("Enter a valid PAN.", 400)
        await vl.kyc_step2_pan(
            client_id, pan, _req(body.pan_holder_name, "PAN holder name"))
    elif action == "aadhaar":
        result = await vl.kyc_step3_aadhaar_init(client_id, redirect_url)
        return {"redirect_url": validate_digilocker_redirect(
            result.get("redirect_url") or result.get("url"), settings)}
    elif action == "gst":
        gst = (body.gst_number or "").strip().upper()
        if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", gst):
            raise TelephonyError("Enter a valid GSTIN.", 400)
        state = await sync_kyc(account)
        if state["account_type"] != "business":
            raise TelephonyError("GST verification applies to businesses.", 400)
        await vl.kyc_step4_gst(client_id, gst)
    elif action == "submit":
        state = await sync_kyc(account)
        if not state["ready_for_submission"]:
            raise TelephonyError(
                "Complete verification and supporting documents first.", 409)
        if not settings.kyc_finalize_verified:
            return {"kyc": state, "warning":
                    "All verification steps are saved with VoiceLink. Final "
                    "submission stays disabled until VoiceLink confirms its "
                    "final-submit endpoint honours client_id and the operator "
                    "enables it in Super Admin -> Telephony -> Settings."}
        await vl.kyc_final_submit(client_id)
    else:  # pragma: no cover - pydantic restricts the action set
        raise TelephonyError("Unknown verification step.", 400)
    return {"kyc": await sync_kyc(account)}


async def upload_kyc_document(user_id: str, document_type: str,
                              content: bytes, content_type: str) -> dict:
    account = await require_account(user_id)
    if document_type not in ("pan", "aadhaar", "gst"):
        raise TelephonyError("Choose the document to upload.", 400)
    if not content or len(content) > 3 * 1024 * 1024:
        raise TelephonyError("Choose a document up to 3 MB.", 400)
    signatures = {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
    }
    if content_type not in signatures or not signatures[content_type]:
        raise TelephonyError(
            "The document format does not match its file type "
            "(PDF, JPG or PNG only).", 400)
    state = await sync_kyc(account)
    doc = state["documents"].get(document_type)
    if not doc or not doc["verified"]:
        raise TelephonyError(
            "Verify this identity detail before uploading its document.", 409)
    ext = {"application/pdf": "pdf", "image/png": "png",
           "image/jpeg": "jpg"}[content_type]
    await vl.kyc_upload_document(account["client_id"], document_type,
                                 f"{document_type}.{ext}", content, content_type)
    return {"kyc": await sync_kyc(account)}


# ---------------------------------------------------------------------------
# Calling balance: SaaS wallet -> VoiceLink client wallet
# ---------------------------------------------------------------------------
async def allocate_from_wallet(user_id: str, amount: float,
                               description: str = "") -> dict:
    account = await require_account(user_id)
    amount = round(float(amount), 2)
    note = f"VoiceLink calling balance {account['id']} {uuid.uuid4().hex[:8]}"
    await repo.deduct_exact(user_id, amount, note=note)
    try:
        await vl.allocate_wallet(account["client_id"], amount,
                                 description or "Calling balance")
    except Exception as e:
        await repo.credit(user_id, amount,
                          note="Refund: calling-balance allocation failed")
        status = getattr(e, "status_code", 502)
        raise TelephonyError(
            f"Could not move balance to the calling account: {e}. "
            "Your wallet was refunded.",
            status if isinstance(status, int) else 502) from None
    try:
        account = await sync_account(account)
    except Exception:
        pass
    return {"wallet": await repo.get_wallet(user_id), "account": account}
