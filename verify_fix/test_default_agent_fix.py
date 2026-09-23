"""Functional check for the 'default agent silent failure' fix.

Simulates the exact scenario that produced the bug:
  * an agent saved with an LLM combo that no longer validates (model removed
    from the catalog, or provider/model mismatch),
  * the worker's `AgentConfig(**rec)` step that used to crash the job silently.
Confirms:
  1. a bad combo now raises a CLEAR, user-surfacable error (what preflight returns),
  2. a valid combo passes,
  3. rag.normalize_query is stable for the prefetch cache key,
  4. BM25/fallback retrieval works offline.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.models import AgentConfig  # noqa: E402
from app.llm_catalog import LLM_MODELS, validate_provider_model  # noqa: E402

# Pick one active model per provider from the real catalog.
active = {}
for m in LLM_MODELS:
    if m.get("status") == "active" and m.get("provider") not in active:
        active[m["provider"]] = m

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_rec(prov: str, model: str, model_id_override=None) -> dict:
    """Shape of repo._agent_dict output (what the worker + preflight receive)."""
    return {
        "id": "agent_test_1",
        "user_id": "user_1",
        "name": "Test Agent",
        "description": "",
        "greeting": "Hello",
        "language": "hi",
        "gender": "female",
        "voice_personality": "friendly",
        "client_rate_per_min": 2.5,
        "memory_enabled": True,
        "recording_enabled": False,
        "max_concurrency": 1,
        "enabled": True,
        "agent_mode": "assistant",
        "announce_text": "",
        "end_after_announcement": False,
        "fallback_response": "",
        "no_response_timeout_seconds": 30,
        "no_response_message": "",
        "providers": {
            "llm": {"id": prov, "config": {"model": model_id_override or model}},
            "stt": {"id": "deepgram_nova2", "config": {}},
            "tts": {"id": "google_wavenet_hi", "config": {}},
            "llm_v2": {"provider": prov, "model_id": model, "config": {}},
        },
        "knowledge": {"text": "Kriscent is an IT services company in Jaipur.", "documents": [], "system_prompt": "", "faq": [{"q": "Rate?", "a": "₹500/hr"}]},
        "created_at": "2026-01-01T00:00:00",
    }


print("== 1. Bad LLM combo (the silent-failure bug) ==")
bad = make_rec("openai", "totally-nonexistent-model-xyz")
try:
    AgentConfig(**bad)
    check("bad combo raises clear error", False, "no exception — bug not caught!")
except ValueError as e:
    msg = str(e)
    check("bad combo raises clear error", True)
    check("error names the problem (surfacable in UI)", "invalid" in msg.lower() or "model" in msg.lower(), msg[:200])
except Exception as e:
    check("bad combo raises clear error (ValueError)", False, f"{type(e).__name__}: {e}")

print("== 2. Valid combo (happy path) ==")
prov = "groq" if "groq" in active else "openai"
m = active[prov]
good = make_rec(prov, m["model_id"])
try:
    cfg = AgentConfig(**good)
    check("valid combo builds AgentConfig", True)
    pair = cfg.providers.get_primary_llm()
    prov2, model2, _ = pair.resolve_llm_provider_model()
    check("resolves to the exact selected model", prov2 == prov and model2 == m["model_id"], f"{prov2}:{model2}")
except Exception as e:
    check("valid combo builds AgentConfig", False, f"{type(e).__name__}: {e}")

print("== 3. Provider/model cross-mismatch (a second common misconfig) ==")
# model that exists but belongs to another provider
other = {p: mm for p, mm in active.items() if p != prov}
target = next(iter(other.values()))
mismatch = make_rec(prov, target["model_id"])
try:
    AgentConfig(**mismatch)
    check("cross-provider mismatch rejected", False, "no exception")
except ValueError as e:
    check("cross-provider mismatch rejected", "belongs to provider" in str(e) or "invalid" in str(e).lower(), str(e)[:160])
except Exception as e:
    check("cross-provider mismatch rejected (ValueError)", False, f"{type(e).__name__}: {e}")

print("== 4. RAG normalize_query (prefetch cache key stability) ==")
from app.rag import normalize_query  # noqa: E402
check(
    "interim vs final text normalize identically",
    normalize_query("kya aapka rate") == normalize_query("Kya, aapka rate?") ,
)
check(
    "punctuation/whitespace stripped",
    normalize_query("  What   is your\n pricing? ") == "what is your pricing",
)

print("== 5. RAG retrieval (offline BM25 fallback) ==")
from app.rag import build_context_detailed  # noqa: E402
from app.models import KnowledgeBase  # noqa: E402
kb = KnowledgeBase(
    text="Kriscent charges 500 rupees per hour. Office is in Jaipur. We do AI agents and web development.",
    faq=[{"q": "What is your rate?", "a": "₹500 per hour, GST extra."}],
)
res = build_context_detailed(kb, "what is your rate per hour?", top_k=3)
check("FAQ hit retrieved for rate question", "500" in res["text"], res["text"][:120])
res2 = build_context_detailed(kb, "where is your office", top_k=3)
check("KB hit retrieved for location question", "Jaipur" in res2["text"], res2["text"][:120])

print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
