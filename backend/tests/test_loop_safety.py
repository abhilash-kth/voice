"""Regression tests for app.agents.loop_safety.

Reproduces the production failure that silenced a live call:

    RuntimeError: Event loop is closed
      grpc/aio/_call.py:761  self._loop.create_task(self._prepare_rpc())

Root cause: the worker "prewarmed" Google TTS by calling ``_ensure_client()``
inside ``asyncio.new_event_loop()`` on a worker thread and then closing that
loop. ``_ensure_client()`` caches a ``TextToSpeechAsyncClient`` whose grpc.aio
channel keeps a reference to the loop it was created on, so every later
``streaming_synthesize()`` on the agent's real loop used the dead loop.

Run with:  cd backend && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keep the runner output readable: these tests assert behaviour, not log text.
logging.getLogger("voice-agent-saas-worker").setLevel(logging.CRITICAL)

from app.agents import loop_safety  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes that mimic the google-cloud-texttospeech / grpc.aio behaviour that broke
# ---------------------------------------------------------------------------
class FakeGrpcChannel:
    """grpc.aio.Channel remembers the running loop at construction time."""

    def __init__(self):
        self._loop = asyncio.get_event_loop()

    def call(self):
        # grpc/aio/_call.py: self._loop.create_task(...) -> _check_closed()
        if self._loop.is_closed():
            raise RuntimeError("Event loop is closed")
        return "audio"


class FakeAsyncClient:
    """texttospeech.TextToSpeechAsyncClient: builds a channel in __init__."""

    def __init__(self):
        self._transport = types.SimpleNamespace(_channel=FakeGrpcChannel())

    def streaming_synthesize(self):
        return self._transport._channel.call()


class FakeGoogleTTS:
    """livekit.plugins.google.TTS: lazily creates + caches _client."""

    def __init__(self, credentials_file=None):
        self._client = None
        self._credentials_file = credentials_file

    def _ensure_client(self):
        if self._client is None:
            self._client = FakeAsyncClient()
        return self._client


class FakeFallbackAdapter:
    """livekit.agents.tts.FallbackAdapter holds the real instances."""

    def __init__(self, instances):
        self._tts_instances = list(instances)


def _run_in_thread_with_temp_loop(fn):
    """What the old prewarm did: new loop on a worker thread, then close it."""
    result = {}

    def _target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result["value"] = loop.run_until_complete(fn()) if asyncio.iscoroutinefunction(fn) else fn()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=5)
    return result.get("value")


class EventLoopPoisoningTest(unittest.TestCase):
    def test_old_offloop_prewarm_poisons_the_client(self):
        """Demonstrates the bug: a client warmed off-loop cannot be used on-loop."""
        tts = FakeGoogleTTS()
        _run_in_thread_with_temp_loop(tts._ensure_client)  # old behaviour
        self.assertIsNotNone(tts._client, "prewarm should have cached a client")

        async def use_it():
            with self.assertRaises(RuntimeError) as cm:
                tts._ensure_client().streaming_synthesize()
            self.assertIn("Event loop is closed", str(cm.exception))

        asyncio.run(use_it())

    def test_guard_drops_a_client_bound_to_a_closed_loop(self):
        tts = FakeGoogleTTS()
        _run_in_thread_with_temp_loop(tts._ensure_client)

        async def use_it():
            dropped = loop_safety.guard_tts_client_loop(tts)
            self.assertEqual(dropped, 1)
            self.assertIsNone(tts._client)
            # ... and the plugin now rebuilds it on the running loop, so audio works.
            self.assertEqual(tts._ensure_client().streaming_synthesize(), "audio")

        asyncio.run(use_it())

    def test_guard_reaches_through_fallback_adapter_and_wrapper(self):
        inner_a, inner_b = FakeGoogleTTS(), FakeGoogleTTS()
        _run_in_thread_with_temp_loop(inner_b._ensure_client)
        adapter = FakeFallbackAdapter([inner_a, inner_b])
        wrapper = types.SimpleNamespace(_inner=adapter, _client=None)

        async def use_it():
            self.assertEqual(loop_safety.guard_tts_client_loop(wrapper), 1)
            self.assertIsNone(inner_b._client)
            self.assertEqual(inner_b._ensure_client().streaming_synthesize(), "audio")

        asyncio.run(use_it())

    def test_guard_keeps_a_client_built_on_the_running_loop(self):
        async def use_it():
            tts = FakeGoogleTTS()
            tts._ensure_client()  # built on this loop, as the plugin would
            self.assertEqual(loop_safety.guard_tts_client_loop(tts), 0)
            self.assertIsNotNone(tts._client)

        asyncio.run(use_it())

    def test_credentials_path_found_through_wrappers(self):
        inner = FakeGoogleTTS(credentials_file="/tmp/key.json")
        adapter = FakeFallbackAdapter([inner])
        wrapper = types.SimpleNamespace(_inner=adapter)
        self.assertEqual(loop_safety.google_tts_credentials_path(wrapper), "/tmp/key.json")


class CredentialCacheTest(unittest.TestCase):
    """The credentials parse is loop-independent and must be shared with the patch."""

    def setUp(self):
        loop_safety.CREDS_CACHE.clear()
        loop_safety._ORIG_LOAD_CREDS = None
        self.calls = []

        def fake_load(filename, scopes=None, **kwargs):
            self.calls.append((filename, tuple(scopes or ())))
            return ("creds-for-" + os.path.basename(filename), "project-1")

        google_mod = types.ModuleType("google")
        auth_mod = types.ModuleType("google.auth")
        default_mod = types.ModuleType("google.auth._default")
        auth_mod.load_credentials_from_file = fake_load
        default_mod.load_credentials_from_file = fake_load
        google_mod.auth = auth_mod
        auth_mod._default = default_mod

        self._saved = {k: sys.modules.get(k) for k in ("google", "google.auth", "google.auth._default")}
        sys.modules["google"] = google_mod
        sys.modules["google.auth"] = auth_mod
        sys.modules["google.auth._default"] = default_mod
        self.auth_mod = auth_mod
        self.default_mod = default_mod

        fd, self.key_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        loop_safety.CREDS_CACHE.clear()
        loop_safety._ORIG_LOAD_CREDS = None
        os.unlink(self.key_path)

    def test_warm_off_loop_feeds_the_patched_loader(self):
        self.assertTrue(loop_safety.install_credential_cache())

        # Warm in a worker thread (no event loop involved at all).
        warmed = _run_in_thread_with_temp_loop(lambda: loop_safety.warm_google_credentials(self.key_path))
        self.assertTrue(warmed)
        self.assertEqual(len(self.calls), 1, "the expensive parse happens once, off-loop")

        # The plugin's own call shape must hit the cache: same key, no re-parse.
        result = self.auth_mod.load_credentials_from_file(
            self.key_path, scopes=[loop_safety.CLOUD_PLATFORM_SCOPE]
        )
        self.assertEqual(result[0], "creds-for-" + os.path.basename(self.key_path))
        self.assertEqual(len(self.calls), 1, "on-loop client build must not re-parse the key")

    def test_cache_is_keyed_per_file_and_scope(self):
        self.assertTrue(loop_safety.install_credential_cache())
        loop_safety.warm_google_credentials(self.key_path)
        self.auth_mod.load_credentials_from_file(self.key_path, scopes=["other-scope"])
        self.assertEqual(len(self.calls), 2, "different scopes must not share a cache entry")
        self.auth_mod.load_credentials_from_file("/tmp/other-key.json", scopes=[loop_safety.CLOUD_PLATFORM_SCOPE])
        self.assertEqual(len(self.calls), 3, "different key files must not share a cache entry")

    def test_warm_tts_off_loop_never_creates_a_client(self):
        """The real fix: warm credentials only; the async client stays un-built."""
        self.assertTrue(loop_safety.install_credential_cache())
        tts = FakeGoogleTTS(credentials_file=self.key_path)

        async def use_it():
            await loop_safety.warm_tts_off_loop(tts)
            # No client yet -> nothing can be bound to the wrong loop.
            self.assertIsNone(tts._client)
            self.assertEqual(len(self.calls), 1, "credentials parsed once, off-loop")
            # First synthesis on the agent loop builds the client on this loop.
            self.assertEqual(tts._ensure_client().streaming_synthesize(), "audio")

        asyncio.run(use_it())

    def test_warm_tts_off_loop_heals_an_already_poisoned_client(self):
        self.assertTrue(loop_safety.install_credential_cache())
        tts = FakeGoogleTTS(credentials_file=self.key_path)
        _run_in_thread_with_temp_loop(tts._ensure_client)  # poisoned by older code

        async def use_it():
            await loop_safety.warm_tts_off_loop(tts)
            self.assertEqual(tts._ensure_client().streaming_synthesize(), "audio")

        asyncio.run(use_it())


if __name__ == "__main__":
    unittest.main(verbosity=2)
