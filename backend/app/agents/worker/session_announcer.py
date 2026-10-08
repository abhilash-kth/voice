from __future__ import annotations

import os
import logging
import time
import hashlib as _hl
from typing import Any, Optional

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .connection_options import _build_conn_options
from .dep_imports import AgentConfig, EGRESS_ENABLED, EGRESS_PUBLIC_BASE_URL, EGRESS_S3_BUCKET, EGRESS_S3_ENDPOINT, EGRESS_S3_REGION, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL

def build_announcement_session(cfg: AgentConfig):
    """Fixed-script "reminder" session: TTS only. No STT, no VAD, no LLM."""
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_tts

    return AgentSession(
        stt=None,
        vad=None,
        llm=None,
        tts=build_tts(cfg),
        conn_options=_build_conn_options(),
        turn_handling={
            # Announcement has no STT/VAD at all, so the library's default
            # "vad"-style turn detector can only fail: every call logs
            # "TurnDetector requires a VAD model" and the session runs on a
            # half-configured detector. "manual" is the honest setting — the
            # script is a single non-interactive playback; end-of-utterance
            # detection is irrelevant here (assistant calls keep their own
            # turn_detection=stt path untouched).
            "turn_detection": "manual",
            "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
            "interruption": {"enabled": False},          # the script must not be cut off
            "preemptive_generation": {"enabled": False},
        },
    )


# ---------------------------------------------------------------------------
# Recording (LiveKit Egress) — best-effort, only if enabled
# ---------------------------------------------------------------------------
async def start_egress(room: str) -> Optional[str]:
    """Start a room-composite egress for `room`, return a public recording URL
    (or None if egress isn't configured). Requires the livekit-egress service."""
    if not EGRESS_ENABLED:
        return None
    if not (EGRESS_S3_BUCKET and EGRESS_PUBLIC_BASE_URL):
        logger.info("🎙️ Recording enabled but Egress storage not configured — skipping.")
        return None
    try:
        from livekit import api

        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            req = api.RoomCompositeEgressRequest(
                room_name=room,
                layout="speaker",
                audio_only=True,
                file_outputs=[api.EncodedFileOutput(
                    file_type=api.EncodedFileType.MP4,
                    filepath=f"recordings/{room}-{int(time.time())}.mp4",
                    s3=api.S3Upload(
                        access_key=os.getenv("EGRESS_S3_ACCESS_KEY", ""),
                        secret=os.getenv("EGRESS_S3_SECRET", ""),
                        bucket=EGRESS_S3_BUCKET,
                        endpoint=EGRESS_S3_ENDPOINT or None,
                        region=EGRESS_S3_REGION,
                    ),
                )],
            )
            res = await client.egress.start_room_composite_egress(req)
            egress_id = getattr(res, "egress_id", "")
            file_results = list(getattr(res, "file_results", []) or [])
            filename = file_results[0].filename if file_results else f"recordings/{room}.mp4"
            logger.info(f"🎙️ Egress started: {egress_id} (status={res.status}) → {filename}")
            return f"{EGRESS_PUBLIC_BASE_URL.rstrip('/')}/{filename}"
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning(f"⚠️ Could not start egress: {e}")
        return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
