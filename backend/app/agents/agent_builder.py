"""
Builds the LiveKit **v1** voice-runtime pieces from a customer-saved AgentConfig.

LiveKit v1 (livekit-agents 1.7.x) replaced ``VoicePipelineAgent`` with the
``Agent``/``AgentSession`` pair, and the per-turn RAG / cross-call memory hooks
moved to ``Agent`` methods. This module exposes small builders so the worker
(``app.agents.worker``) can assemble a session without caring about provider
details.

All LiveKit plugin imports are done lazily inside functions so the FastAPI /
management layer can boot even when the livekit packages aren't installed in
that particular interpreter (e.g. a lightweight CI or a machine that only runs
the API).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from ..models import AgentConfig, KnowledgeBase
from ..config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    LLM_MODEL,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# ---------------------------------------------------------------------------
# Google TTS voice normalisation
# ---------------------------------------------------------------------------
# Google's streaming_synthesize endpoint rejects every Wavenet/Standard/Neural2
# voice with ``400 Currently, only Chirp 3: HD voices are supported``. Chirp 3: HD
# uses the "<locale>-Chirp3-HD-<name>" form with 8 multilingual speakers (Leda,
# Kore, Zephyr, Aoede, Charon, Fenrir, Orus, Puck) available across all supported
# locales. So any legacy voice stored in an agent config is transparently mapped
# to a Chirp 3: HD voice for the same locale.
_CHIRP3_VOICES = {
    "female": "Leda",       # alternates: Kore, Zephyr, Aoede
    "male": "Charon",       # alternates: Fenrir, Orus, Puck
}


def _resolve_tts_voice(language: str, raw_voice: Optional[str]) -> str:
    """Return a voice name that Google's streaming endpoint accepts.

    A voice already set to a Chirp 3 or Gemini name is passed through unchanged.
    An empty value defaults to Chirp 3: HD. Any legacy Wavenet/Standard/Neural2
    voice is remapped to a Chirp 3: HD voice for the same locale.
    """
    v = (raw_voice or "").strip()
    if v and ("chirp" in v.lower() or "gemini" in v.lower()):
        return v
    if not v:
        return f"{language or 'hi-IN'}-Chirp3-HD-Leda"
    # Derive the locale from a legacy voice name like "hi-IN-Wavenet-A"
    parts = v.split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        locale = f"{parts[0]}-{parts[1]}"
    else:
        locale = language or "hi-IN"
    return f"{locale}-Chirp3-HD-Leda"


# ---------------------------------------------------------------------------
# Provider → plugin construction
# ---------------------------------------------------------------------------
def build_llm(cfg: AgentConfig) -> Any:
    from livekit.plugins.openai import LLM
    from openai import AsyncOpenAI

    sel = cfg.providers.llm
    overrides = sel.config or {}
    provider_id = sel.id

    # Providers that speak the OpenAI chat-completions protocol. Each maps to a
    # base_url + the env key that holds the credential.
    if provider_id.startswith("groq"):
        base_url = overrides.get("base_url") or "https://api.groq.com/openai/v1"
        api_key = overrides.get("api_key") or GROQ_API_KEY
        key_env = "GROQ_API_KEY"
    elif provider_id.startswith("openrouter"):
        base_url = overrides.get("base_url") or "https://openrouter.ai/api/v1"
        api_key = overrides.get("api_key") or OPENROUTER_API_KEY
        key_env = "OPENROUTER_API_KEY"
    else:
        base_url = overrides.get("base_url") or None
        api_key = overrides.get("api_key") or OPENAI_API_KEY
        key_env = "OPENAI_API_KEY"

    if not api_key:
        raise RuntimeError(
            f"No API key for LLM provider '{provider_id}'. Set '{key_env}' "
            "in backend/.env (or pass api_key in the agent's llm config)."
        )

    # Default model: an explicit agent-config model wins, then the env override for
    # THAT provider, then a fast, quota-friendly default.
    #   * Groq DEPRECATED + shut down the Llama chat models (08/16/26) in favour of
    #     openai/gpt-oss-120b / -20b -> that is the Groq default.
    #   * OpenRouter uses the LLM_MODEL env (e.g. google/gemma-4-31b-it:free) with a
    #     sensible free default; any :free model can be chosen per-agent.
    #   * OpenAI/other -> gpt-4o-mini.
    import os as _os
    # Catalog default for THIS provider (so a sparse config still picks the right model).
    from ..catalog import get_provider as _get_provider
    _cat_model = (_get_provider("llm", provider_id) or {}).get("model")
    if sel.id.startswith("openrouter"):
        env_model = _os.getenv("LLM_MODEL") or _os.getenv("OPENAI_MODEL")
        default_model = _cat_model or "google/gemma-4-31b-it:free"
    elif sel.id.startswith("groq"):
        env_model = _os.getenv("GROQ_MODEL")
        default_model = _cat_model or "openai/gpt-oss-120b"
    else:
        env_model = _os.getenv("OPENAI_MODEL")
        default_model = _cat_model or "gpt-4o-mini"
    model = overrides.get("model") or env_model or default_model

    # Reasoning control, model-aware. Some reasoning models have no "none" level:
    #   * gpt-oss -> "low"  (valid on Groq, minimal chain-of-thought)
    #   * qwen    -> "none" (disables thinking entirely)
    #   * Gemma (OpenRouter) -> "none" (no reasoning tokens; fast for a receptionist).
    #   * OpenRouter free models -> default off so we don't spend the tiny free
    #     quota on chain-of-thought.
    low = model.lower()
    if "qwen" in low or "gemma" in low:
        default_reasoning = "none"
    elif "gpt-oss" in low:
        default_reasoning = "low"
    else:
        default_reasoning = "none"
    reasoning = overrides.get("reasoning_effort", default_reasoning)

    if sel.id.startswith("groq") and "qwen" in low:
        logger.warning(
            f"⚠️ LLM model '{model}' is a Groq *reasoning* model with a 200k tokens/day "
            "quota. It 429s (rate-limit) after a handful of calls, then LiveKit retries "
            "3x with backoff → 15–20s 'thinking' stalls. For a voice agent pick "
            "'openai/gpt-oss-120b' or 'openai/gpt-oss-20b' instead "
            "(see .env GROQ_MODEL / agent config)."
        )
    if sel.id.startswith("groq") and any(m in low for m in ("llama-3.3-70b", "llama-3.1-8b")):
        logger.warning(
            f"⚠️ LLM model '{model}' was DEPRECATED by Groq (shutdown 08/16/26). "
            "Use 'openai/gpt-oss-120b' (or 'openai/gpt-oss-20b') instead."
        )
    if sel.id.startswith("openrouter") and ":free" not in model and "free" not in low:
        logger.info(
            f"ℹ️ OpenRouter model '{model}' is not a :free model — it will bill your "
            "OpenRouter credits. Use a ':free' model for the demo (see LLM_MODEL)."
        )

    # `max_retries=0` on the SDK client disables the *OpenAI‑SDK* retry layer. We
    # deliberately cap the retry budget from a single place (the session's
    # `conn_options`, see worker.py) so a transient DNS blip or provider 429 fails
    # fast instead of stacking retries and freezing the call for ~20s.
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    return LLM(
        client=client,
        model=model,
        temperature=float(overrides.get("temperature", 0.1)),
        max_completion_tokens=int(overrides.get("max_tokens", 300)),
        # See `reasoning` above. For gpt-oss keep it low so the model doesn't spend
        # time on a long chain-of-thought that also risks leaking into the spoken
        # reply (the worker's clean_reply_text strips <think>/<reasoning> anyway).
        reasoning_effort=reasoning,
    )


def build_stt(cfg: AgentConfig) -> Any:
    sel = cfg.providers.stt
    overrides = sel.config or {}

    if sel.id.startswith("google"):
        from livekit.plugins.google import STT
        # v1 uses a list of languages (e.g. ["hi-IN"]) rather than a single code.
        lang = overrides.get("language", "hi-IN")
        languages = [lang] if isinstance(lang, str) and "," not in lang else [x.strip() for x in lang.split(",")]
        return STT(
            languages=languages,
            model=overrides.get("model", "latest"),
            credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
        )

    from livekit.plugins.deepgram import STT
    keywords = overrides.get("keywords") or [
        ("Kriscent", 10.0),
        ("Kota", 6.0),
    ]
    return STT(
        model=overrides.get("model", "nova-2"),
        language=overrides.get("language", "hi"),
        keywords=keywords,
        interim_results=bool(overrides.get("interim_results", True)),
        # Defaults are good, but set explicitly so noise handling stays on:
        #   * vad_events=True   -> Deepgram's built-in VAD rejects non-speech / noise
        #     frames before they ever reach the LLM.
        #   * no_delay=True      -> emit transcripts as soon as they're final (no
        #     extra buffering delay).
        #   * filler_words=True  -> boost turn-detector accuracy.
        vad_events=bool(overrides.get("vad_events", True)),
        no_delay=bool(overrides.get("no_delay", True)),
        filler_words=bool(overrides.get("filler_words", True)),
        api_key=overrides.get("api_key") or DEEPGRAM_API_KEY or None,
    )


def build_tts(cfg: AgentConfig) -> Any:
    sel = cfg.providers.tts
    overrides = sel.config or {}

    if sel.id.startswith("google"):
        from livekit.plugins.google import TTS
        # Google's streaming endpoint only accepts Chirp 3: HD voices; any legacy
        # Wavenet/Standard/Neural2 voice is remapped to Chirp 3 HD automatically.
        language = overrides.get("language", "hi-IN")
        voice = _resolve_tts_voice(language, overrides.get("voice"))
        return TTS(
            voice_name=voice,
            language=language,
            credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
        )

    if sel.id.startswith("elevenlabs"):
        from livekit.plugins.elevenlabs import TTS
        return TTS(
            voice_id=overrides.get("voice", "pNInz6obpgDQGcFmaJgB"),
            model=overrides.get("model", "eleven_multilingual_v2"),
            language=overrides.get("language", "hi"),
        )

    if sel.id.startswith("openrouter"):
        # OpenRouter exposes an OpenAI-compatible /audio/speech endpoint, so we use
        # LiveKit's OpenAI TTS plugin and just point it at OpenRouter's base URL.
        #   * model : e.g. deepgram/flux-tts:free (FREE, English-only), 
        #             fish-audio/s2.1-pro-free:free (FREE, multilingual, voice-clone),
        #             hexgrad/kokoro-82m (multilingual incl. Hindi, PAID), etc.
        #   * voice : model-dependent. Must be one of the model's supported_voices
        #             (see https://openrouter.ai/api/v1/models?output_modalities=speech).
        #             Fish-Audio has NO preset voice (voice-cloning only) — a plain
        #             voice string won't synthesize for it, so it's not a drop-in.
        #   * response_format: "mp3" (reliable, decoded to 24 kHz by LiveKit). "pcm"
        #             is lower latency but may carry a model-specific sample rate.
        import os as _os
        from livekit.plugins.openai import TTS

        # Resolve the model from (in order): agent config -> env -> catalog default.
        # This mirrors how the frontend saves it, and lets a bare config work too.
        from ..catalog import get_provider
        cat = get_provider("tts", sel.id) or {}
        model = (
            overrides.get("model")
            or _os.getenv("LLM_TTS_MODEL", "")
            or cat.get("model")
            or "deepgram/flux-tts:free"
        )
        api_key = overrides.get("api_key") or OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError(
                "OpenRouter TTS needs OPENROUTER_API_KEY (see backend/.env) or an "
                "api_key in the agent's tts config."
            )
        # Voices for the models we ship in the catalog; anything else MUST carry an
        # explicit `voice` (OpenRouter rejects a missing/blank voice unless the
        # provider documents a default). Fish-Audio has no preset voice at all — it
        # is clone-only, so a plain voice string will not synthesize for it.
        default_voices = {
            "deepgram/flux-tts:free": "flux-bree-en",
            "hexgrad/kokoro-82m": "af_bella",
            "microsoft/mai-voice-2-flash": "en-US-Harper:MAI-Voice-2",
            "qwen/qwen-audio-3.0-tts-flash": "loongjohn",
        }
        voice = overrides.get("voice") or cat.get("voice") or default_voices.get(model)
        if not voice:
            # No usable voice (this is the case for clone-only Fish Audio). Do NOT
            # crash the call — fall back to the free Flux voice and warn loudly so
            # the demo keeps working and the operator sees what happened.
            logger.warning(
                f"⚠️ OpenRouter TTS model '{model}' has no preset voice (it is "
                "voice-cloning only) and no `voice` was set. Falling back to "
                "'deepgram/flux-tts:free' (English) so the call does not fail. "
                "Fix the agent's TTS config with a valid `voice` or pick another "
                "TTS provider."
            )
            model = "deepgram/flux-tts:free"
            voice = "flux-bree-en"
        return TTS(
            model=model,
            voice=voice,
            api_key=api_key,
            base_url=overrides.get("base_url") or "https://openrouter.ai/api/v1",
            response_format=overrides.get("response_format", "mp3"),
        )

    raise ValueError(f"Unsupported TTS provider: {sel.id}")


def build_vad() -> Any:
    from livekit.plugins import silero
    return silero.VAD.load(
        min_speech_duration=0.1,
        min_silence_duration=0.5,
        prefix_padding_duration=0.2,
        activation_threshold=0.45,
    )


# ---------------------------------------------------------------------------
# System prompt builder (persona + business facts + FAQ)
# ---------------------------------------------------------------------------
def _flatten_knowledge(kb: KnowledgeBase) -> list[str]:
    """Flatten every knowledge source into a list of bullet lines.

    Unlike ``build_context`` (which retrieves *only the relevant* chunks for a
    single query), this returns the whole knowledge base so it can be baked into
    the static system prompt once. That keeps the chat context identical on every
    turn, which lets LiveKit's preemptive generation survive (see the note on
    ``on_user_turn_completed``) and is what makes replies fast.
    """
    blocks = []
    manual = (kb.text or "").strip()
    if manual:
        blocks.append(manual)
    for doc in kb.documents or []:
        name = doc.get("name", "document")
        content = doc.get("content") or doc.get("text") or ""
        if content.strip():
            blocks.append(f"[{name}]\n{content.strip()}")
    return blocks


def build_instructions(cfg: AgentConfig, query_context: str = "") -> str:
    persona = cfg.voice_personality or "friendly"
    lang = cfg.language or "hi"

    lines = [
        f"You are {cfg.name}, a {persona} voice receptionist.",
        "Speak only 1 short Hindi or Hinglish sentence per reply.",
        "No English analysis. No markdown. No lists. No emojis.",
        f"Language: {lang}.",
    ]
    # Natural, human-like behaviour: concise, non-repetitive, never salesy, and
    # conversational rather than scripted. This is what makes calls feel human.
    lines.append(
        "Behave like a warm human receptionist. Never repeat yourself, never push "
        "the same offer, never read out a list of services unprompted, and never "
        "give a long preamble. Answer exactly what was asked, then stop. If the "
        "caller is satisfied or has no further questions, briefly close the "
        "conversation. Never mention being an AI, a robot, or a bot."
    )

    extra = cfg.knowledge.system_prompt
    if extra:
        lines.append("")
        lines.append("Instructions from the business owner:")
        lines.append(extra.strip())

    facts = _flatten_knowledge(cfg.knowledge)
    if facts:
        lines.append("")
        lines.append("Business facts you know (use these when answering):")
        lines.extend(f"- {f}" for f in facts)

    if query_context:
        lines.append("")
        lines.append("Relevant business facts to use when answering:")
        lines.append(query_context)

    faq = getattr(cfg.knowledge, "faq", None) or []
    if faq:
        lines.append("")
        lines.append(
            "Frequently asked questions. When the caller asks something that "
            "matches one of these, answer with its official answer VERBATIM "
            "(do not paraphrase or add extra info):"
        )
        for item in faq:
            q = item.get("q", "")
            a = item.get("a", "")
            if q and a:
                lines.append(f"- Q: {q}\n  A: {a}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v1 Agent (subclass) — static knowledge + cross-call memory + greeting
# ---------------------------------------------------------------------------
def build_voice_agent(
    cfg: AgentConfig,
    *,
    greeting: str = "",
    prior_memory: str = "",
    lead_data: Optional[dict] = None,
) -> "Any":
    """Return a LiveKit v1 ``Agent`` instance wired for this config.

    The returned agent:
      * speaks ``greeting`` when the session enters (LiveKit's ``on_enter``),
      * has the full knowledge base baked into its static system prompt, and
      * seeds the conversation with ``prior_memory`` (cross-call memory).

    The knowledge base is NOT injected per-turn: mutating the chat context in
    ``on_user_turn_completed`` would invalidate LiveKit's preemptive generation
    (the fast path that starts the LLM while you are still speaking), doubling
    latency. Baking it in once keeps the context stable so replies stay fast.
    """
    from livekit.agents import Agent, llm
    from livekit.agents import get_job_context

    # The FULL knowledge base is baked into the static system prompt so the model
    # always has every fact. This keeps the chat context byte-identical on every
    # turn, which is what lets LiveKit's preemptive generation survive — the
    # single biggest latency win. (Do NOT mutate the context per-turn.)
    instructions = build_instructions(cfg)

    # Auto hang-up: when the conversation is finished the LLM calls `end_call`,
    # which shuts the job down so the call is cut AND the billing is finalized.
    # We make the trigger explicit so the model reliably hangs up on its own and
    # doesn't leave the caller in a silent, open call.
    instructions += (
        "\n\nAUTOMATIC HANG-UP: You must call the `end_call` tool (once) at the point "
        "the conversation is over — as soon as the caller says goodbye / thanks you "
        "clearly, has had their question answered, or has nothing left to ask. Say a "
        "short closing line (e.g. \"Dhanyavaad, good day!\") and then call `end_call` "
        "immediately. Never end the call mid-answer — only once the exchange is "
        "genuinely finished, and never ask follow-up questions after ending."
    )

    async def _end_call() -> str:
        """End this call and hang up. Call it once the conversation is finished."""
        ctx = get_job_context(required=False)
        if ctx is None:
            return "No job context; call not ended."
        # Physically cut the call: delete the LiveKit room so the caller/SIP
        # participant is disconnected (not left in a silent, open call).
        room = getattr(ctx.room, "name", None)
        if room:
            try:
                from ..telephony import end_active_room
                await end_active_room(room)
            except Exception as e:
                logger.warning(f"end_call: could not delete room {room}: {e}")
        ctx.shutdown()
        return "Call ended."

    # `name="end_call"` keeps the LLM-visible tool name in sync with the prompt
    # (otherwise it would default to "_end_call" and the model might not call it).
    end_call_tool = llm.function_tool(
        _end_call,
        name="end_call",
        description="End the call and hang up. Call this once the conversation is finished.",
    )

    # Cross-call memory becomes part of the initial conversation history, so it
    # influences every turn without being re-inserted.
    chat_ctx = llm.ChatContext()
    if lead_data:
        # For bulk-call campaigns, give the agent the lead's details (from the
        # uploaded file) so it can address them by name / reference their data.
        lead_blurb = ", ".join(f"{k}: {v}" for k, v in (lead_data or {}).items() if v)
        chat_ctx.add_message(
            role="system",
            content=(
                "You are now speaking with a specific caller from a contact list.\n"
                f"This caller's details: {lead_blurb or '(none)'}.\n"
                "Use the caller's name naturally when it is known, and reference their "
                "details when relevant."
            ),
        )
    if prior_memory:
        chat_ctx.add_message(
            role="system",
            content="Prior conversation with this customer:\n" + prior_memory,
        )

    class _VoiceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self.greeting = greeting
            super().__init__(
                instructions=instructions,
                chat_ctx=chat_ctx,
                # Registered tools let the LLM hang up the call once the
                # conversation concludes (auto-cut).
                tools=[end_call_tool],
                # NOTE: turn-handling (endpointing / interruption / preemptive
                # generation) is set on the AgentSession (build_assistant_session),
                # where LiveKit actually reads the interruption min_duration/window.
                # Keeping it there is the single source of truth; do NOT also set it
                # here or the two can disagree.
            )

        async def on_enter(self) -> None:
            if self.greeting:
                # Wait until a participant is linked and audio output is ready
                # before speaking, so outbound/SIP greetings aren't lost while
                # the number is still ringing.
                try:
                    room_io = getattr(self.session, "room_io", None)
                    if room_io is not None and hasattr(room_io, "wait_for_ready"):
                        await asyncio.wait_for(room_io.wait_for_ready(), timeout=60)
                except asyncio.TimeoutError:
                    logger.warning("Timed out waiting for a participant to join — greeting anyway.")
                except Exception as e:
                    logger.warning(f"wait_for_ready failed; greeting anyway: {e}")
                await self.session.say(self.greeting, allow_interruptions=True)

        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            """Hook that runs after the user finishes speaking.

            LiveKit's ``AgentSession`` ``await``s this hook, so it must be a
            coroutine (``async def``). We deliberately do NOT add anything to
            ``turn_ctx`` here: the knowledge base is already baked into the static
            system prompt, and mutating ``turn_ctx`` would invalidate LiveKit's
            preemptive generation and force a slow second LLM call. Keeping this a
            no-op is what makes replies feel instant.
            """
            return

    return _VoiceAgent()


# ---------------------------------------------------------------------------
# Announcement / fixed-script "reminder" agent — no STT, no LLM
# ---------------------------------------------------------------------------
def build_announce_agent(
    cfg: AgentConfig,
    *,
    announce_text: str = "",
) -> "Any":
    """Return a LiveKit v1 ``Agent`` that only plays a fixed script and hangs up.

    Used for "reminder"/"inform-only" calls: the agent answers, reads the script
    aloud via TTS, then ends the call. It never listens (no STT) and never
    generates a reply (no LLM). The customer is not billed for STT/LLM.
    """
    from livekit.agents import Agent
    from livekit.agents import llm

    text = (announce_text or cfg.greeting or "").strip()
    if not text:
        raise ValueError(
            "Announcement agent has no script. Set announce_text (or greeting) on the agent."
        )

    class _AnnounceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            super().__init__(
                # No LLM: a still/empty instruction set. Everything is hardcoded.
                instructions="You are a one-way announcement. Do not use tools.",
                chat_ctx=llm.ChatContext(),
                turn_handling={
                    "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
                    "interruption": {"enabled": False},  # script should not be cut off
                    "preemptive_generation": {"enabled": False},
                },
            )

        async def on_enter(self) -> None:
            # Wait for the participant/audio to be ready so the script isn't cut off.
            try:
                room_io = getattr(self.session, "room_io", None)
                if room_io is not None and hasattr(room_io, "wait_for_ready"):
                    await asyncio.wait_for(room_io.wait_for_ready(), timeout=60)
            except Exception as e:
                logger.warning(f"wait_for_ready failed; playing announcement anyway: {e}")
            # Play the fixed script, then end the call gracefully. We delete the
            # LiveKit room so the caller is physically disconnected (otherwise the
            # browser/SIP participant would be left in a silent, open call), then
            # shut the job down — which runs the worker's finalize_billing shutdown
            # callback so the call is marked completed.
            speech = self.session.say(text, allow_interruptions=False)
            await speech
            try:
                from livekit.agents import get_job_context
                ctx = get_job_context(required=False)
                if ctx is not None:
                    room = getattr(ctx.room, "name", None)
                    if room:
                        try:
                            from ..telephony import end_active_room
                            await end_active_room(room)
                        except Exception as e:
                            logger.warning(f"announcement: could not delete room {room}: {e}")
                    ctx.shutdown()
                else:
                    self.session.shutdown(drain=True)
                logger.info("📢 Announcement finished — closing call.")
            except Exception as e:
                logger.warning(f"could not close announcement session: {e}")

    return _AnnounceAgent()
