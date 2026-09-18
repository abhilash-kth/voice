"""Tests for app.db event-loop affinity.

A Prisma client (engine + httpx pool) belongs to the loop that connected it.
The LiveKit worker used to connect it from a throwaway loop inside
``asyncio.to_thread(...)``, which left a client that reported itself connected
while every query on the agent loop hung until it timed out:

    agent lookup attempt 1/2 failed (3.01s):      <- bare TimeoutError, no message

These tests use a fake ``prisma_client`` so they run without Prisma/DB access.

Run with:  cd backend && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keep the runner output readable: these tests assert behaviour, not log text.
logging.getLogger("voice-agent-saas-db").setLevel(logging.CRITICAL)


class FakePrisma:
    """Mimics prisma_client.Prisma: connect() binds to the running loop."""

    instances: list = []

    def __init__(self):
        self.connected = False
        self.connected_loop = None
        self.connect_calls = 0
        self.disconnect_should_hang = False
        FakePrisma.instances.append(self)

    def is_connected(self) -> bool:
        return self.connected

    async def connect(self, timeout=None):
        if self.connected:
            raise RuntimeError("Client has already been connected.")
        self.connect_calls += 1
        self.connected = True
        self.connected_loop = asyncio.get_running_loop()

    async def disconnect(self):
        if self.disconnect_should_hang:
            await asyncio.sleep(30)  # simulate an unusable foreign-loop engine
        self.connected = False
        self.connected_loop = None


def _install_fake_prisma():
    mod = types.ModuleType("prisma_client")
    errors = types.ModuleType("prisma_client.errors")

    class PrismaError(Exception):
        pass

    mod.Prisma = FakePrisma
    mod.errors = errors
    errors.PrismaError = PrismaError
    sys.modules["prisma_client"] = mod
    sys.modules["prisma_client.errors"] = errors


class DbLoopAffinityTest(unittest.TestCase):
    def setUp(self):
        FakePrisma.instances.clear()
        self._saved = {k: sys.modules.get(k) for k in ("prisma_client", "prisma_client.errors")}
        _install_fake_prisma()
        sys.modules.pop("app.db", None)
        self.db = importlib.import_module("app.db")

    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        sys.modules.pop("app.db", None)

    def test_connect_then_reuse_on_same_loop(self):
        async def scenario():
            await self.db.init()
            client = self.db.get_prisma()
            self.assertEqual(client.connect_calls, 1)
            await self.db.init()  # no-op
            self.assertEqual(client.connect_calls, 1)
            self.assertTrue(self.db.is_connected())

        asyncio.run(scenario())

    def test_client_connected_on_a_foreign_loop_is_not_reused(self):
        """The bug: connect on loop A, then serve queries from loop B."""

        async def connect_on_a():
            await self.db.init()

        asyncio.run(connect_on_a())  # loop A is closed when this returns
        client = self.db.get_prisma()
        self.assertTrue(client.is_connected(), "the raw client still thinks it is connected")

        async def use_from_b():
            # Loop-affine view says "not connected here"...
            self.assertFalse(self.db.is_connected())
            # ... and init() recovers by reconnecting on THIS loop.
            await self.db.init()
            self.assertTrue(self.db.is_connected())
            self.assertIs(client.connected_loop, asyncio.get_running_loop())

        asyncio.run(use_from_b())

    def test_unusable_client_is_replaced_when_disconnect_hangs(self):
        async def connect_on_a():
            await self.db.init()
            self.db.get_prisma().disconnect_should_hang = True

        asyncio.run(connect_on_a())
        first = self.db.get_prisma()

        async def use_from_b():
            await self.db.init()
            self.assertIsNot(self.db.get_prisma(), first, "a fresh client must replace the stuck one")
            self.assertTrue(self.db.is_connected())
            self.assertEqual(self.db.get_prisma().connect_calls, 1)

        asyncio.run(use_from_b())

    def test_concurrent_init_connects_once(self):
        async def scenario():
            await asyncio.gather(*(self.db.init() for _ in range(10)))
            self.assertEqual(self.db.get_prisma().connect_calls, 1)

        asyncio.run(scenario())

    def test_shutdown_clears_loop_affinity(self):
        async def scenario():
            await self.db.init()
            await self.db.shutdown()
            self.assertFalse(self.db.is_connected())
            await self.db.init()  # reconnectable
            self.assertTrue(self.db.is_connected())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
