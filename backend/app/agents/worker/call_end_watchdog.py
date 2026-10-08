"""Call-end watchdog: ends the job once the human caller has actually left
(any disconnect reason), so LiveKit shutdown callbacks (finalize_billing)
always run. Contains greeting/no-response speech-end bookkeeping.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule).
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")


def build_call_end_watchdog(ctx, session, cfg, agent_mode, agent_id, greeting,
                            state_tracker, usage, call_closed, call_finished,
                            closing_in_progress, reply_tracker, agent_holder,
                            _cancel_no_response, _cancel_pending):

    # Watchdog: end the call when the caller leaves for any reason (closing the
    # tab, network drop, or clicking "Leave"). Closing the session unblocks
    # session.start(), which lets the job shut down and run finalize_billing.
    async def watch_call_end():
        """End this job only after the human caller has actually left.

        close_on_disconnect is off so a goodbye can finish. That also meant a
        hung-up browser could leave the only worker process stuck inside
        session.start(). The next call — after the user picked a different
        agent — was dispatched to nobody and stayed silent.

        A caller who is still connected is not idle. Silence is the no-response
        timer's job. This watcher only releases the job once the caller is gone.
        """
        room = ctx.room
        released = {"done": False}
        saw_human = {"yes": False}
        gone_since = {"t": 0.0}

        def _kind(participant) -> int:
            kind = getattr(participant, "kind", 0)
            try:
                return int(kind)
            except Exception:
                return 0

        def _is_human(participant) -> bool:
            if participant is None or participant == getattr(room, "local_participant", None):
                return False
            # 1 ingress, 2 egress, 4 agent — not the person on the call.
            if _kind(participant) in (1, 2, 4):
                return False
            identity = (getattr(participant, "identity", "") or "").lower()
            if identity.startswith("eg_") or "egress" in identity:
                return False
            return True

        def _humans():
            try:
                return [p for p in room.remote_participants.values() if _is_human(p)]
            except Exception:
                return []

        async def _release(reason: str, source: str = "timeout"):
            if released["done"]:
                return
            released["done"] = True
            call_closed["done"] = True
            logger.info(
                "[CALL_END_REQUESTED] source=%s reason=%s room=%s agent_id=%s",
                source, reason, getattr(ctx.room, "name", ""), agent_id,
            )
            _cancel_pending()
            _cancel_no_response()
            fallback_task = reply_tracker.get("fallback_say")
            if fallback_task is not None and not fallback_task.done():
                fallback_task.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.shutdown(drain=False)
            except Exception as e:
                logger.warning("session.shutdown on caller leave failed: %r", e)

            room_name = getattr(ctx.room, "name", None)
            if room_name:
                try:
                    from app.telephony import end_active_room
                    await end_active_room(room_name)
                except Exception:
                    pass

            try:
                ctx.shutdown()
            except Exception as e:
                logger.warning("ctx.shutdown failed: %r", e)

            logger.info("[CALL_ENDED] room=%s agent_id=%s reason=%s", getattr(ctx.room, "name", ""), agent_id, reason)
            call_finished.set()

        def _on_connected(participant):
            if not _is_human(participant):
                return
            saw_human["yes"] = True
            gone_since["t"] = 0.0
            logger.info("[AGENT_JOINED] room=%s Caller joined: %s", getattr(room, "name", ""), getattr(participant, "identity", "?"))

        def _on_disconnected(participant):
            if not _is_human(participant):
                return
            if _humans():
                return
            gone_since["t"] = time.time()
            logger.info("👤 Caller disconnected: %s (grace period active)", getattr(participant, "identity", "?"))

        room.on("participant_connected", _on_connected)
        room.on("participant_disconnected", _on_disconnected)
        initial_humans = _humans()
        if initial_humans:
            saw_human["yes"] = True
            logger.info("[AGENT_JOINED] room=%s Caller already in room (%d): %s", getattr(room, "name", ""), len(initial_humans), [p.identity for p in initial_humans])

        try:
            while not released["done"]:
                await asyncio.sleep(0.5)
                # Announcement agent manages its own completion — don't interfere while it's playing
                if agent_mode == "announcement":
                    ag = agent_holder.get("agent")
                    if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
                        continue

                humans = _humans()
                if humans:
                    saw_human["yes"] = True
                    gone_since["t"] = 0.0
                    continue
                if not saw_human["yes"]:
                    continue
                if gone_since["t"] == 0.0:
                    gone_since["t"] = time.time()
                    continue
                # Generous 12-second grace period (NOT 1.5s!) before deciding caller is truly gone
                if time.time() - gone_since["t"] >= 12.0:
                    await _release("user_ended", source="timeout")
                    return
        except asyncio.CancelledError:
            return
        finally:
            try:
                room.off("participant_connected", _on_connected)
                room.off("participant_disconnected", _on_disconnected)
            except Exception:
                pass

    async def _backup_opening_line():
        """Speak the greeting/script if on_enter never started.

        A connected browser call that stays silent is the bug this covers.
        """
        try:
            await asyncio.sleep(8)
        except asyncio.CancelledError:
            return
        if call_closed["done"] or closing_in_progress["done"]:
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False):
            return
        if state_tracker.get("state") == "speaking":
            return
        if any((t.get("text") or "").strip() and t.get("role") == "agent" for t in usage["transcripts"]):
            return
        if agent_mode == "announcement":
            line = (getattr(cfg, "announce_text", "") or greeting or "").strip()
        else:
            line = (greeting or "").strip()
        if not line:
            logger.warning("🛟 No greeting or script configured — nothing to speak")
            return
        logger.warning("🛟 Opening line had not started — speaking it now (%s)", agent_mode)
        try:
            # Assistant-mode greetings must be interruptible (the primary path
            # in agent_builder.speak_opening_line passes True now too); this
            # fallback line was the same hard-protected pattern. Announcements
            # stay one-way.
            handle = session.say(line, allow_interruptions=(agent_mode != "announcement"))
            waiter = getattr(handle, "wait_for_playout", None)
            if callable(waiter):
                await asyncio.wait_for(waiter(), timeout=45)
            elif handle is not None:
                await asyncio.wait_for(handle, timeout=45)
            logger.info("✅ Backup opening line finished")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("backup opening line failed: %s: %r", type(e).__name__, e)

    # Deduplication check: if another agent has already connected to this room, exit immediately
    try:
        remote_agents = [
            p for p in ctx.room.remote_participants.values()
            if getattr(p, "kind", None) == 4
            or getattr(p, "is_agent", False)
            or (getattr(p, "identity", "") or "").startswith("agent-")
        ]
        if remote_agents:
            logger.warning(
                "⚠️ Duplicate agent already present in room %s (%s). Exiting this runner to prevent duplicate audio.",
                getattr(ctx.room, "name", ""),
                [getattr(p, "identity", "") for p in remote_agents],
            )
            call_closed["done"] = True
            ctx.shutdown()
            return
    except Exception as e:
        logger.debug("duplicate agent check: %r", e)

    opening_backup = asyncio.create_task(_backup_opening_line())
    return watch_call_end
