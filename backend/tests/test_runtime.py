from __future__ import annotations

import asyncio
import sys
import types
import unittest
import warnings
from pathlib import Path

# Keep these tests independent of the optional LiveKit/provider installations.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.runtime import (  # noqa: E402
    GoogleTTSLoopGuard,
    LLMTimingWrapper,
    TTSLoopOwnershipError,
    new_turn_timing,
    reset_turn_timing,
    wrap_tts_for_timing,
)
from app.agents import bootstrap  # noqa: E402
from app.billing import calculate_call_cost  # noqa: E402


class _FakeClient:
    def __init__(self, loop):
        self._loop = loop


class _FakeGoogleOwner:
    def __init__(self, client=None):
        self._client = client
        self.ensure_loop = None
        self.ensure_calls = 0

    async def _ensure_client(self):
        self.ensure_calls += 1
        self.ensure_loop = asyncio.get_running_loop()
        self._client = _FakeClient(self.ensure_loop)


class _FakeGoogleTTS:
    def __init__(self, owner, *, raises=False):
        self._tts = owner
        self.raises = raises

    def synthesize(self, text, **kwargs):
        async def _stream():
            if self.raises:
                raise RuntimeError("Event loop is closed")
            yield text

        return _stream()

    def stream(self, **kwargs):
        return _FakeTTSStream(raises=self.raises)


class _FakeTTSStream:
    def __init__(self, raises=False):
        self.text = []
        self.raises = raises

    def push_text(self, text):
        self.text.append(text)

    def __aiter__(self):
        async def _items():
            if self.raises:
                raise RuntimeError("Event loop is closed")
            yield b"audio"

        return _items()

    async def aclose(self):
        return None


class _FakeStreamingTTS:
    def synthesize(self, text, **kwargs):
        async def _stream():
            yield b"audio"

        return _stream()

    def stream(self, **kwargs):
        return _FakeTTSStream()


class _FakeLLMStream:
    def __aiter__(self):
        async def _items():
            yield "first"

        return _items()


class _FakeLLMContext:
    async def __aenter__(self):
        return _FakeLLMStream()

    async def __aexit__(self, *args):
        return None


class _FakeLLM:
    def chat(self, *args, **kwargs):
        return _FakeLLMContext()


class RuntimeTests(unittest.TestCase):
    def test_tts_client_is_created_on_current_agent_loop(self):
        async def exercise():
            old_loop = asyncio.new_event_loop()
            owner = _FakeGoogleOwner(_FakeClient(old_loop))
            guarded = GoogleTTSLoopGuard(_FakeGoogleTTS(owner))
            output = [chunk async for chunk in guarded.synthesize("hello")]
            self.assertEqual(output, ["hello"])
            self.assertIs(owner.ensure_loop, asyncio.get_running_loop())
            self.assertIs(owner._client._loop, asyncio.get_running_loop())
            self.assertEqual(owner.ensure_calls, 1)
            old_loop.close()

        asyncio.run(exercise())

    def test_cross_loop_client_is_not_reused(self):
        async def exercise():
            foreign_loop = asyncio.new_event_loop()
            old_client = _FakeClient(foreign_loop)
            owner = _FakeGoogleOwner(old_client)
            guarded = GoogleTTSLoopGuard(_FakeGoogleTTS(owner))
            [chunk async for chunk in guarded.synthesize("hello")]
            self.assertIsNot(owner._client, old_client)
            self.assertIs(owner._client._loop, asyncio.get_running_loop())
            foreign_loop.close()

        asyncio.run(exercise())

    def test_event_loop_recovery_does_not_leave_coroutine_warning(self):
        async def exercise():
            owner = _FakeGoogleOwner(_FakeClient(asyncio.get_running_loop()))
            guarded = GoogleTTSLoopGuard(_FakeGoogleTTS(owner, raises=True))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with self.assertRaises(TTSLoopOwnershipError):
                    [chunk async for chunk in guarded.synthesize("hello")]
            self.assertFalse(any(issubclass(w.category, RuntimeWarning) for w in caught))
            self.assertIsNone(owner._client)

            owner2 = _FakeGoogleOwner(_FakeClient(asyncio.get_running_loop()))
            guarded2 = GoogleTTSLoopGuard(_FakeGoogleTTS(owner2, raises=True))
            stream = guarded2.stream()
            with warnings.catch_warnings(record=True) as caught_stream:
                warnings.simplefilter("always")
                with self.assertRaises(TTSLoopOwnershipError):
                    [chunk async for chunk in stream]
            self.assertFalse(any(issubclass(w.category, RuntimeWarning) for w in caught_stream))
            self.assertIsNone(owner2._client)

        asyncio.run(exercise())

    def test_real_stream_timing_records_request_and_authoritative_audio(self):
        async def exercise():
            timing = new_turn_timing()
            timing["speech_end"] = __import__("time").time() - 0.02
            timing["first_token"] = __import__("time").time() - 0.01
            tts = wrap_tts_for_timing(_FakeStreamingTTS(), timing)
            [chunk async for chunk in tts.synthesize("hello")]
            self.assertEqual(timing["tts_request_source"], "synthesize")
            self.assertGreater(timing["tts_request_delay_ms"], 0)
            self.assertGreater(timing["last_speech_end_to_first_audio"], 0)

            timing2 = new_turn_timing()
            timing2["first_token"] = __import__("time").time() - 0.01
            tts2 = wrap_tts_for_timing(_FakeStreamingTTS(), timing2)
            stream = tts2.stream()
            stream.push_text("hello")
            [chunk async for chunk in stream]
            self.assertEqual(timing2["tts_request_source"], "stream.push_text")
            self.assertGreater(timing2["first_audio"], 0)

        asyncio.run(exercise())

    def test_turn_to_llm_scheduling_and_first_token_are_observed(self):
        async def exercise():
            timing = new_turn_timing()
            timing["turn_detected"] = __import__("time").time() - 0.01
            llm = LLMTimingWrapper(_FakeLLM(), timing)
            async with llm.chat() as stream:
                [chunk async for chunk in stream]
            self.assertGreaterEqual(timing["llm_start"], timing["turn_detected"])
            self.assertGreater(timing["first_token"], timing["llm_start"])

        asyncio.run(exercise())

    def test_duplicate_turn_lifecycle_does_not_reuse_timing(self):
        timing = new_turn_timing()
        first_id = timing["turn_id"]
        reset_turn_timing(timing)
        self.assertEqual(timing["turn_id"], first_id + 1)
        self.assertEqual(timing["first_token"], 0.0)
        self.assertEqual(timing["tts_request"], 0.0)

    def test_ssl_prewarm_covers_imported_httpx_references(self):
        """The aliases captured by httpx modules must use the warm context too."""
        original_modules = {
            name: sys.modules.get(name)
            for name in (
                "livekit",
                "livekit.agents",
                "livekit.agents.utils",
                "httpx",
                "httpx._config",
                "httpx._client",
                "httpx._transports",
                "httpx._transports.default",
            )
        }
        bootstrap._cache.clear()
        calls = []

        def original_httpx(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("the blocking httpx SSL helper was called")

        original_livekit = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("the blocking LiveKit SSL helper was called")
        )
        http_context = types.SimpleNamespace(_create_ssl_context=original_livekit)
        fake_utils = types.ModuleType("livekit.agents.utils")
        fake_utils.http_context = http_context
        fake_livekit = types.ModuleType("livekit")
        fake_livekit.__path__ = []
        fake_agents = types.ModuleType("livekit.agents")
        fake_agents.__path__ = []
        fake_httpx = types.ModuleType("httpx")
        fake_httpx.__path__ = []
        fake_config = types.ModuleType("httpx._config")
        fake_config.create_ssl_context = original_httpx
        fake_client = types.ModuleType("httpx._client")
        # Simulate ``from httpx._config import create_ssl_context`` before the
        # worker's bootstrap runs.
        fake_client.create_ssl_context = original_httpx
        fake_transports = types.ModuleType("httpx._transports")
        fake_transports.__path__ = []
        fake_transport_default = types.ModuleType("httpx._transports.default")
        fake_transport_default.create_ssl_context = original_httpx
        fake_modules = {
            "livekit": fake_livekit,
            "livekit.agents": fake_agents,
            "livekit.agents.utils": fake_utils,
            "httpx": fake_httpx,
            "httpx._config": fake_config,
            "httpx._client": fake_client,
            "httpx._transports": fake_transports,
            "httpx._transports.default": fake_transport_default,
        }
        sys.modules.update(fake_modules)
        try:
            bootstrap.install_ssl_context_cache()
            context = fake_config.create_ssl_context()
            self.assertIs(context, fake_client.create_ssl_context())
            self.assertIs(context, fake_transport_default.create_ssl_context())
            self.assertIs(context, http_context._create_ssl_context())
            self.assertEqual(calls, [])
        finally:
            bootstrap._cache.clear()
            for name, old in original_modules.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old

    def test_billing_calculation_remains_provider_based(self):
        result = calculate_call_cost(
            duration_seconds=60,
            stt_seconds=10,
            llm_input_tokens=100,
            llm_output_tokens=50,
            tts_chars=200,
            llm_provider_id="groq_llama_3_3_70b",
            stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi",
        )
        self.assertIn("total_cost_inr", result)
        self.assertGreaterEqual(result["total_cost_inr"], 0)
        self.assertIn("tts_cost_inr", result)


if __name__ == "__main__":
    unittest.main()
