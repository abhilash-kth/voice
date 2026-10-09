"""Greeting selection + lead-template rendering for the call's opening hello.

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule).
"""
from __future__ import annotations

from .dep_imports import leadfile


def select_greeting(cfg, lead_data) -> str:
    """Agent greeting: configured, or language-appropriate default; campaign
    {column} placeholders then substituted from lead_data. Verbatim."""
    if (cfg.greeting or "").strip():
        greeting = cfg.greeting
    elif (getattr(cfg, "language", "hi") or "hi").lower().startswith("en"):
        greeting = f"Hello, this is {cfg.name}. How can I help you?"
    else:
        greeting = f"Namaste! Main {cfg.name} hoon. Aap kaise madad kar sakta hoon?"
    # Dynamic script: substitute {column} placeholders with this lead's values
    # (used by bulk-call campaigns so every call is personalized).
    greeting = leadfile.render_template(greeting, lead_data)
    return greeting
