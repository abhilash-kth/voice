"""Super Admin-managed telephony settings.

The single ``TelephonyConfig`` DB row is the runtime source of truth for the
VoiceLink marketplace. Existing ``backend/.env`` telephony values are used
only to seed that row the first time an operator opens the settings screen
(and as an emergency fallback if the DB row/table is unavailable). After the
row exists, telephony values are changed from Super Admin, not by editing
``.env``.

The VoiceLink API token/password are encrypted with the same Fernet keyring
used for provider credentials. Plaintext exists only in this process's
short-lived settings cache; public/admin views expose masked values only.

Bootstrap values deliberately stay in ``.env``: DATABASE_URL, JWT_SECRET,
ADMIN_CONFIG_ENC_KEY(S), and LIVEKIT_URL/API key/API secret (the frozen
voice worker must use the same LiveKit server credentials).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from .. import config, repo
from .credential_service import mask_secret
from .crypto import decrypt_secret, encrypt_secret
from .telephony_policy import TelephonyError

logger = logging.getLogger("voice-agent-saas-telephony-settings")

DEFAULT_API_BASE_URL = "https://app.voicelink.co.in/api/v1"
_CACHE_TTL_SECONDS = 15.0
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_AUDIO_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,19}$")
_TERMS_HOSTS = {"app.voicelink.co.in", "voicelink.co.in"}


@dataclass
class TelephonySettings:
    source: str = "super_admin"  # super_admin | environment_fallback
    default_sip_trunk_id: str = ""
    voicelink_api_base_url: str = DEFAULT_API_BASE_URL
    voicelink_api_token: str = field(default="", repr=False)
    voicelink_api_token_masked: str = ""
    voicelink_username: str = ""
    voicelink_password: str = field(default="", repr=False)
    voicelink_password_masked: str = ""
    voicelink_shared_trunk_username: str = ""
    voicelink_shared_trunk_password: str = field(default="", repr=False)
    voicelink_shared_trunk_password_masked: str = ""
    voicelink_sip_host: str = "sip.voicelink.co.in"
    voicelink_sip_port: int = 3300
    voicelink_tech_prefix: str = "45454"
    voicelink_transport_type: int = 1
    voicelink_audio_formats: list[str] = field(
        default_factory=lambda: ["alaw", "ulaw"])
    voicelink_wallet_bypass: bool = False
    voicelink_kyc_terms_url: str = ""
    voicelink_kyc_redirect_hosts: list[str] = field(default_factory=list)
    kyc_finalize_verified: bool = False
    livekit_sip_host: str = ""
    livekit_sip_port: int = 5060
    frontend_url: str = "http://localhost:3000"
    public_api_url: str = ""
    updated_at: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.static_token
                    or (self.voicelink_username and self.voicelink_password))

    @property
    def static_token(self) -> str:
        token = (self.voicelink_api_token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token


_cache: Optional[TelephonySettings] = None
_cache_at: float = 0.0
_cache_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------

def _clean_host(value: Any, label: str, *, allow_blank: bool = False) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if not host:
        if allow_blank:
            return ""
        raise TelephonyError(f"{label} is required.", 400)
    if not _HOST_RE.fullmatch(host):
        raise TelephonyError(
            f"{label} must be a hostname only (no scheme, port or spaces).", 400)
    return host


LIVEKIT_SIP_HOST_PLACEHOLDER = "{client_id}"


def _clean_livekit_sip_host(value: Any, *, allow_blank: bool = False) -> str:
    """Validate a LiveKit SIP host, optionally with one {client_id} alias."""
    host = str(value or "").strip().lower().rstrip(".")
    if not host:
        if allow_blank:
            return ""
        raise TelephonyError("LiveKit SIP host is required.", 400)
    placeholder_count = host.count(LIVEKIT_SIP_HOST_PLACEHOLDER)
    without_placeholder = host.replace(LIVEKIT_SIP_HOST_PLACEHOLDER, "")
    if placeholder_count > 1 or "{" in without_placeholder \
            or "}" in without_placeholder:
        raise TelephonyError(
            "LiveKit SIP host may contain only one {client_id} placeholder.",
            400)
    _clean_host(host.replace(LIVEKIT_SIP_HOST_PLACEHOLDER, "client123"),
                "LiveKit SIP host")
    return host


def resolve_livekit_sip_host(value: Any, client_id: Any) -> str:
    """Resolve the per-client LiveKit SIP host alias used for VoiceLink."""
    template = _clean_livekit_sip_host(value, allow_blank=True)
    if not template:
        return ""
    label = re.sub(r"[^a-z0-9-]", "-", str(client_id or "").strip().lower())
    label = re.sub(r"-+", "-", label).strip("-")[:32].strip("-") or "client"
    return _clean_host(
        template.replace(LIVEKIT_SIP_HOST_PLACEHOLDER, label),
        "LiveKit SIP host")


def _clean_url(value: Any, label: str, *, allow_http: bool = False,
               allow_blank: bool = False, default: str = "") -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        if allow_blank:
            return ""
        return default
    try:
        parsed = urlparse(raw)
        _ = parsed.port  # raises on malformed ports
    except Exception:
        raise TelephonyError(f"{label} is not a valid URL.", 400) from None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise TelephonyError(
            f"{label} must not contain credentials, a query or a fragment.", 400)
    host = (parsed.hostname or "").lower()
    if not host or not _HOST_RE.fullmatch(host):
        raise TelephonyError(f"{label} must contain a valid hostname.", 400)
    local = host in ("localhost", "127.0.0.1")
    schemes = {"https", "http"} if (allow_http or local) else {"https"}
    if parsed.scheme.lower() not in schemes:
        raise TelephonyError(f"{label} must use HTTPS.", 400)
    return raw


def _clean_terms_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    clean = _clean_url(raw, "KYC terms URL")
    host = (urlparse(clean).hostname or "").lower()
    if host not in _TERMS_HOSTS:
        raise TelephonyError(
            "KYC terms URL must be hosted on app.voicelink.co.in or "
            "voicelink.co.in.", 400)
    return clean


def _clean_hosts(values: Any, label: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    out: list[str] = []
    for value in values or []:
        host = _clean_host(value, label, allow_blank=True)
        if host and host not in out:
            out.append(host)
    return out


def _clean_audio_formats(values: Any) -> list[str]:
    if isinstance(values, str):
        values = values.split(",")
    out: list[str] = []
    for value in values or []:
        fmt = str(value or "").strip().lower()
        if not fmt:
            continue
        if not _AUDIO_RE.fullmatch(fmt):
            raise TelephonyError(
                "Audio formats must be simple codec names such as alaw, ulaw.",
                400)
        if fmt not in out:
            out.append(fmt)
    if not out:
        raise TelephonyError("At least one audio format is required.", 400)
    return out


def _clean_text_no_spaces(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if any(ch.isspace() for ch in text):
        raise TelephonyError(f"{label} must not contain spaces.", 400)
    return text


def _safe(cleaner, value, fallback):
    try:
        return cleaner(value)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Settings construction
# ---------------------------------------------------------------------------

def env_fallback_settings() -> TelephonySettings:
    """Current env values, used for the first DB seed / emergency fallback."""
    token = str(config.VOICELINK_API_TOKEN or "")
    password = str(config.VOICELINK_PASSWORD or "")
    settings = TelephonySettings(
        source="environment_fallback",
        default_sip_trunk_id=str(config.DEFAULT_SIP_TRUNK_ID or "").strip(),
        voicelink_api_base_url=_safe(
            lambda v: _clean_url(v, "VoiceLink API base URL",
                                 default=DEFAULT_API_BASE_URL),
            config.VOICELINK_API_BASE_URL, DEFAULT_API_BASE_URL),
        voicelink_api_token=token,
        voicelink_api_token_masked=mask_secret(token),
        voicelink_username=str(config.VOICELINK_USERNAME or "").strip(),
        voicelink_password=password,
        voicelink_password_masked=mask_secret(password),
        voicelink_sip_host=_safe(
            lambda v: _clean_host(v, "VoiceLink SIP host"),
            config.VOICELINK_SIP_HOST, "sip.voicelink.co.in"),
        voicelink_sip_port=int(config.VOICELINK_SIP_PORT or 3300),
        voicelink_tech_prefix=re.sub(
            r"\D", "", str(config.VOICELINK_TECH_PREFIX or "")),
        voicelink_transport_type=int(config.VOICELINK_TRANSPORT_TYPE or 1),
        voicelink_audio_formats=_safe(
            _clean_audio_formats, list(config.VOICELINK_AUDIO_FORMATS or []),
            ["alaw", "ulaw"]),
        voicelink_wallet_bypass=bool(config.VOICELINK_WALLET_BYPASS),
        voicelink_kyc_terms_url=_safe(
            _clean_terms_url, config.VOICELINK_KYC_TERMS_URL, ""),
        voicelink_kyc_redirect_hosts=_safe(
            lambda v: _clean_hosts(v, "KYC redirect host"),
            list(config.VOICELINK_KYC_REDIRECT_HOSTS or []), []),
        kyc_finalize_verified=bool(
            config.VOICELINK_CLIENT_KYC_FINALIZE_VERIFIED),
        livekit_sip_host=_safe(
            lambda v: _clean_livekit_sip_host(v, allow_blank=True),
            config.LIVEKIT_SIP_HOST, ""),
        livekit_sip_port=int(config.LIVEKIT_SIP_PORT or 5060),
        frontend_url=_safe(
            lambda v: _clean_url(
                v, "Customer app URL", allow_http=True,
                default="http://localhost:3000"),
            config.FRONTEND_URL, "http://localhost:3000"),
        public_api_url=_safe(
            lambda v: _clean_url(v, "Public API URL", allow_http=True,
                                 allow_blank=True),
            config.PUBLIC_API_URL, ""),
    )
    return settings


def _decrypt(enc: str) -> str:
    if not enc:
        return ""
    try:
        return decrypt_secret(enc)
    except Exception:
        logger.warning(
            "Stored VoiceLink credential could not be decrypted; re-enter it "
            "in Super Admin -> Telephony -> Settings.")
        return ""


def _settings_from_record(record: dict) -> TelephonySettings:
    return TelephonySettings(
        source="super_admin",
        default_sip_trunk_id=str(record.get("default_sip_trunk_id") or "").strip(),
        voicelink_api_base_url=_safe(
            lambda v: _clean_url(v, "VoiceLink API base URL",
                                 default=DEFAULT_API_BASE_URL),
            record.get("voicelink_api_base_url"), DEFAULT_API_BASE_URL),
        voicelink_api_token=_decrypt(record.get("voicelink_api_token_enc") or ""),
        voicelink_api_token_masked=str(
            record.get("voicelink_api_token_masked") or ""),
        voicelink_username=str(record.get("voicelink_username") or "").strip(),
        voicelink_password=_decrypt(record.get("voicelink_password_enc") or ""),
        voicelink_password_masked=str(
            record.get("voicelink_password_masked") or ""),
        voicelink_shared_trunk_username=str(
            record.get("voicelink_shared_trunk_username") or "").strip(),
        voicelink_shared_trunk_password=_decrypt(
            record.get("voicelink_shared_trunk_password_enc") or ""),
        voicelink_shared_trunk_password_masked=str(
            record.get("voicelink_shared_trunk_password_masked") or ""),
        voicelink_sip_host=_safe(
            lambda v: _clean_host(v, "VoiceLink SIP host"),
            record.get("voicelink_sip_host"), "sip.voicelink.co.in"),
        voicelink_sip_port=int(record.get("voicelink_sip_port") or 3300),
        voicelink_tech_prefix=re.sub(
            r"\D", "", str(record.get("voicelink_tech_prefix") or "")),
        voicelink_transport_type=int(
            record.get("voicelink_transport_type") or 1),
        voicelink_audio_formats=_safe(
            _clean_audio_formats,
            record.get("voicelink_audio_formats") or "alaw,ulaw",
            ["alaw", "ulaw"]),
        voicelink_wallet_bypass=bool(record.get("voicelink_wallet_bypass")),
        voicelink_kyc_terms_url=_safe(
            _clean_terms_url, record.get("voicelink_kyc_terms_url"), ""),
        voicelink_kyc_redirect_hosts=_safe(
            lambda v: _clean_hosts(v, "KYC redirect host"),
            record.get("voicelink_kyc_redirect_hosts") or "", []),
        kyc_finalize_verified=bool(record.get("kyc_finalize_verified")),
        livekit_sip_host=_safe(
            lambda v: _clean_host(v, "LiveKit SIP host", allow_blank=True),
            record.get("livekit_sip_host"), ""),
        livekit_sip_port=int(record.get("livekit_sip_port") or 5060),
        frontend_url=_safe(
            lambda v: _clean_url(
                v, "Customer app URL", allow_http=True,
                default="http://localhost:3000"),
            record.get("frontend_url"), "http://localhost:3000"),
        public_api_url=_safe(
            lambda v: _clean_url(v, "Public API URL", allow_http=True,
                                 allow_blank=True),
            record.get("public_api_url"), ""),
        updated_at=str(record.get("updated_at") or ""),
    )


def _record_from_settings(settings: TelephonySettings) -> dict:
    token_enc, token_masked = ("", "")
    if settings.voicelink_api_token:
        token_enc, token_masked = encrypt_secret(settings.voicelink_api_token)
    password_enc, password_masked = ("", "")
    if settings.voicelink_password:
        password_enc, password_masked = encrypt_secret(settings.voicelink_password)
    shared_password_enc, shared_password_masked = ("", "")
    if settings.voicelink_shared_trunk_password:
        shared_password_enc, shared_password_masked = encrypt_secret(
            settings.voicelink_shared_trunk_password)
    return {
        "default_sip_trunk_id": settings.default_sip_trunk_id,
        "voicelink_api_base_url": settings.voicelink_api_base_url,
        "voicelink_api_token_enc": token_enc,
        "voicelink_api_token_masked": token_masked,
        "voicelink_username": settings.voicelink_username,
        "voicelink_password_enc": password_enc,
        "voicelink_password_masked": password_masked,
        "voicelink_shared_trunk_username": (
            settings.voicelink_shared_trunk_username),
        "voicelink_shared_trunk_password_enc": shared_password_enc,
        "voicelink_shared_trunk_password_masked": shared_password_masked,
        "voicelink_sip_host": settings.voicelink_sip_host,
        "voicelink_sip_port": settings.voicelink_sip_port,
        "voicelink_tech_prefix": settings.voicelink_tech_prefix,
        "voicelink_transport_type": settings.voicelink_transport_type,
        "voicelink_audio_formats": ",".join(settings.voicelink_audio_formats),
        "voicelink_wallet_bypass": settings.voicelink_wallet_bypass,
        "voicelink_kyc_terms_url": settings.voicelink_kyc_terms_url,
        "voicelink_kyc_redirect_hosts": ",".join(
            settings.voicelink_kyc_redirect_hosts),
        "kyc_finalize_verified": settings.kyc_finalize_verified,
        "livekit_sip_host": settings.livekit_sip_host,
        "livekit_sip_port": settings.livekit_sip_port,
        "frontend_url": settings.frontend_url,
        "public_api_url": settings.public_api_url,
    }


def public_view(settings: TelephonySettings) -> dict:
    return {
        "source": settings.source,
        "configured": settings.configured,
        "encryption_key_configured": bool(
            os.getenv("ADMIN_CONFIG_ENC_KEY")
            or os.getenv("ADMIN_CONFIG_ENC_KEYS")),
        "default_sip_trunk_id": settings.default_sip_trunk_id,
        "voicelink_api_base_url": settings.voicelink_api_base_url,
        "voicelink_api_token_configured": bool(settings.voicelink_api_token),
        "voicelink_api_token_masked": settings.voicelink_api_token_masked,
        "voicelink_username": settings.voicelink_username,
        "voicelink_password_configured": bool(settings.voicelink_password),
        "voicelink_password_masked": settings.voicelink_password_masked,
        "voicelink_shared_trunk_username": (
            settings.voicelink_shared_trunk_username),
        "voicelink_shared_trunk_password_configured": bool(
            settings.voicelink_shared_trunk_password),
        "voicelink_shared_trunk_password_masked": (
            settings.voicelink_shared_trunk_password_masked),
        "voicelink_sip_host": settings.voicelink_sip_host,
        "voicelink_sip_port": settings.voicelink_sip_port,
        "voicelink_tech_prefix": settings.voicelink_tech_prefix,
        "voicelink_transport_type": settings.voicelink_transport_type,
        "voicelink_audio_formats": list(settings.voicelink_audio_formats),
        "voicelink_wallet_bypass": settings.voicelink_wallet_bypass,
        "voicelink_kyc_terms_url": settings.voicelink_kyc_terms_url,
        "voicelink_kyc_redirect_hosts": list(
            settings.voicelink_kyc_redirect_hosts),
        "kyc_finalize_verified": settings.kyc_finalize_verified,
        "livekit_sip_host": settings.livekit_sip_host,
        "livekit_sip_port": settings.livekit_sip_port,
        "frontend_url": settings.frontend_url,
        "public_api_url": settings.public_api_url,
        "updated_at": settings.updated_at,
    }


# ---------------------------------------------------------------------------
# Cache + DB access
# ---------------------------------------------------------------------------

def invalidate_cache() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _set_cache(settings: TelephonySettings) -> TelephonySettings:
    global _cache, _cache_at
    _cache = settings
    _cache_at = time.monotonic()
    return settings


async def get_settings(*, force: bool = False) -> TelephonySettings:
    global _cache, _cache_at
    if (not force and _cache is not None
            and time.monotonic() - _cache_at < _CACHE_TTL_SECONDS):
        return _cache
    async with _cache_lock:
        if (not force and _cache is not None
                and time.monotonic() - _cache_at < _CACHE_TTL_SECONDS):
            return _cache
        try:
            record = await repo.get_telephony_config(include_secrets=True)
        except Exception as e:
            logger.warning(
                "TelephonyConfig unavailable (%s); using env fallback. Run "
                "Prisma db push/generate if the table has not been created.",
                type(e).__name__)
            return _set_cache(env_fallback_settings())
        if record:
            return _set_cache(_settings_from_record(record))
        return _set_cache(env_fallback_settings())


async def ensure_settings_row() -> TelephonySettings:
    """Return DB settings, seeding the singleton row from env on first use."""
    try:
        record = await repo.get_telephony_config(include_secrets=True)
    except Exception:
        record = None
    if record:
        return _set_cache(_settings_from_record(record))

    seeded = env_fallback_settings()
    try:
        created = await repo.create_telephony_config(
            _record_from_settings(seeded))
    except Exception as e:
        logger.warning(
            "Could not seed TelephonyConfig (%s); returning env fallback.",
            type(e).__name__)
        created = None
    if created:
        return _set_cache(_settings_from_record(created))
    # A concurrent request may have created it first.
    try:
        record = await repo.get_telephony_config(include_secrets=True)
    except Exception:
        record = None
    if record:
        return _set_cache(_settings_from_record(record))
    return _set_cache(seeded)


async def init() -> TelephonySettings:
    settings = await get_settings(force=True)
    logger.info(
        "Telephony settings loaded (source=%s, configured=%s)",
        settings.source, settings.configured)
    return settings


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

def _normalize_patch(patch: dict) -> dict:
    out: dict[str, Any] = {}

    if "default_sip_trunk_id" in patch:
        out["default_sip_trunk_id"] = _clean_text_no_spaces(
            patch.get("default_sip_trunk_id"), "Default SIP trunk ID")
    if "voicelink_api_base_url" in patch:
        out["voicelink_api_base_url"] = _clean_url(
            patch.get("voicelink_api_base_url"), "VoiceLink API base URL",
            default=DEFAULT_API_BASE_URL)

    if patch.get("clear_voicelink_api_token"):
        out["voicelink_api_token_enc"] = ""
        out["voicelink_api_token_masked"] = ""
    elif str(patch.get("voicelink_api_token") or ""):
        try:
            enc, masked = encrypt_secret(str(patch["voicelink_api_token"]))
        except Exception:
            raise TelephonyError(
                "Could not encrypt the VoiceLink API token. Check "
                "ADMIN_CONFIG_ENC_KEY.", 500) from None
        out["voicelink_api_token_enc"] = enc
        out["voicelink_api_token_masked"] = masked

    if "voicelink_username" in patch:
        out["voicelink_username"] = _clean_text_no_spaces(
            patch.get("voicelink_username"), "VoiceLink username")

    if patch.get("clear_voicelink_password"):
        out["voicelink_password_enc"] = ""
        out["voicelink_password_masked"] = ""
    elif str(patch.get("voicelink_password") or ""):
        try:
            enc, masked = encrypt_secret(str(patch["voicelink_password"]))
        except Exception:
            raise TelephonyError(
                "Could not encrypt the VoiceLink password. Check "
                "ADMIN_CONFIG_ENC_KEY.", 500) from None
        out["voicelink_password_enc"] = enc
        out["voicelink_password_masked"] = masked

    if "voicelink_shared_trunk_username" in patch:
        out["voicelink_shared_trunk_username"] = _clean_text_no_spaces(
            patch.get("voicelink_shared_trunk_username"),
            "Existing shared VoiceLink trunk username")

    if patch.get("clear_voicelink_shared_trunk_password"):
        out["voicelink_shared_trunk_password_enc"] = ""
        out["voicelink_shared_trunk_password_masked"] = ""
    elif str(patch.get("voicelink_shared_trunk_password") or ""):
        try:
            enc, masked = encrypt_secret(
                str(patch["voicelink_shared_trunk_password"]))
        except Exception:
            raise TelephonyError(
                "Could not encrypt the shared VoiceLink trunk password. "
                "Check ADMIN_CONFIG_ENC_KEY.", 500) from None
        out["voicelink_shared_trunk_password_enc"] = enc
        out["voicelink_shared_trunk_password_masked"] = masked

    if "voicelink_sip_host" in patch:
        out["voicelink_sip_host"] = _clean_host(
            patch.get("voicelink_sip_host"), "VoiceLink SIP host")
    if "voicelink_sip_port" in patch:
        out["voicelink_sip_port"] = int(patch["voicelink_sip_port"])
    if "voicelink_tech_prefix" in patch:
        prefix = str(patch.get("voicelink_tech_prefix") or "").strip()
        if prefix and not prefix.isdigit():
            raise TelephonyError("Tech prefix must contain digits only.", 400)
        out["voicelink_tech_prefix"] = prefix
    if "voicelink_transport_type" in patch:
        out["voicelink_transport_type"] = int(patch["voicelink_transport_type"])
    if "voicelink_audio_formats" in patch:
        out["voicelink_audio_formats"] = ",".join(
            _clean_audio_formats(patch.get("voicelink_audio_formats")))
    if "voicelink_wallet_bypass" in patch:
        out["voicelink_wallet_bypass"] = bool(patch["voicelink_wallet_bypass"])
    if "voicelink_kyc_terms_url" in patch:
        out["voicelink_kyc_terms_url"] = _clean_terms_url(
            patch.get("voicelink_kyc_terms_url"))
    if "voicelink_kyc_redirect_hosts" in patch:
        out["voicelink_kyc_redirect_hosts"] = ",".join(_clean_hosts(
            patch.get("voicelink_kyc_redirect_hosts"), "KYC redirect host"))
    if "kyc_finalize_verified" in patch:
        out["kyc_finalize_verified"] = bool(patch["kyc_finalize_verified"])
    if "livekit_sip_host" in patch:
        out["livekit_sip_host"] = _clean_livekit_sip_host(
            patch.get("livekit_sip_host"), allow_blank=True)
    if "livekit_sip_port" in patch:
        out["livekit_sip_port"] = int(patch["livekit_sip_port"])
    if "frontend_url" in patch:
        out["frontend_url"] = _clean_url(
            patch.get("frontend_url"), "Customer app URL", allow_http=True,
            default="http://localhost:3000")
    if "public_api_url" in patch:
        out["public_api_url"] = _clean_url(
            patch.get("public_api_url"), "Public API URL", allow_http=True,
            allow_blank=True)
    return out


async def update_settings(patch: dict) -> TelephonySettings:
    current = await ensure_settings_row()
    if current.source != "super_admin":
        raise TelephonyError(
            "Telephony settings could not be saved because the database "
            "settings table is unavailable. Run Prisma db push and generate, "
            "then restart the backend.", 503)
    repo_patch = _normalize_patch(patch)
    if not repo_patch:
        raise TelephonyError("No telephony settings changes were supplied.", 400)
    updated = await repo.update_telephony_config(repo_patch)
    if not updated:
        raise TelephonyError("Telephony settings could not be saved.", 500)
    settings = _set_cache(_settings_from_record(updated))
    # Never keep using a login token minted with old panel credentials.
    try:
        from . import voicelink_client as vl
        vl.reset_auth_cache()
    except Exception:
        pass
    return settings


async def test_connection() -> dict:
    settings = await get_settings(force=True)
    if not settings.configured:
        raise TelephonyError(
            "Enter a VoiceLink API token or username/password, save, then "
            "test the connection.", 400)
    from . import telephony_account as accounts
    from . import voicelink_client as vl
    profile = accounts.safe_profile(await vl.profile())
    return {"ok": True, "profile": profile}
