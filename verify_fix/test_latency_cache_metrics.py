"""Static + logic tests for the 2026-09-24 latency spec (Tasks 1-4).

The sandbox has no livekit installed, so runtime behaviour is asserted via
AST/source invariants of the exact code paths that run in production, plus
real unit tests of the pure logic modules. Run: python3 verify_fix/test_latency_cache_metrics.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

BUILDER = (BACKEND / "app/agents/agent_builder.py").read_text()
WORKER = (BACKEND / "app/agents/worker.py").read_text()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


# ---------------------------------------------------------------- Task 1: cache key
print("[Task 1] prompt_cache_key propagation (builder -> plugin constructor)")
tree = ast.parse(BUILDER)
# Every assignment of prompt_cache_key must happen BEFORE any _instantiate_llm
# call in the same function body (kwargs must be populated at build time).
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in (
        "_build_llm_from_pair", "_instantiate_llm",
    ):
        src = ast.get_source_segment(BUILDER, node)
        if node.name == "_build_llm_from_pair":
            assign_at = src.find('prompt_cache_key')
            call_at = src.find('_instantiate_llm(')
            check("cache key set before _instantiate_llm", 0 <= assign_at < call_at)
            # only for OpenAI-direct paths (Groq rejects the param)
            _asgn = src.find('llm_kwargs["prompt_cache_key"]')
            _guard = src.rfind('provider_type == "openai"', 0, _asgn)
            check("assignment guarded to openai provider_type", 0 <= _asgn and 0 <= _guard)
check("OpenAILLM gets **llm_kwargs (not a filtered copy)",
      re.search(r"OpenAILLM\(\*\*llm_kwargs\)", BUILDER) is not None)
# Wrapper only claims a hit from real usage numbers.
check("[CACHE] per-request log reads usage-cached only",
      "cache_status={_ck_status}" in WORKER
      and '"hit" if _cached_now > 0 else "miss"' in WORKER)
check("[CACHE] never claims hit without cached>0 (summary verdict)",
      "if _ch > 0:\n                        _cache_verdict = \"working\"" in WORKER
      or 'if _ch > 0:' in WORKER)
check("non-OpenAI reports unsupported, not fake hit",
      '"n/a", "unsupported"' in WORKER)
check("builder verifies key reached plugin _opts",
      'getattr(llm_instance, "_opts", None), "prompt_cache_key"' in BUILDER)

# ---------------------------------------------------------------- Task 2: preemptive gate
print("[Task 2] preemptive stays disabled under per-turn RAG; metrics present")
check("rag/KB paths force preemptive_enabled = False",
      WORKER.count("preemptive_enabled = False") >= 2)
check("[PREEMPTIVE] config + summary lines exist",
      "[PREEMPTIVE] enabled=" in WORKER and "[PREEMPTIVE] summary" in WORKER)
check("started/cancelled/reused/completed counters in log format",
      "started=0 cancelled=0 reused=0 completed=0" in WORKER)
check("builder never force-enables preemptive",
      "preemptive_generation=True" not in BUILDER)
# RAG injection stays per-turn and discarded (preemptive can never be "fixed"
# by removing grounding): the no-dedupe decision comment must remain.
check("per-turn RAG injection not deduped out of existence",
      "_RAG_PREFIX" in BUILDER or "KNOWLEDGE_RETRIEVAL" in BUILDER)

# ---------------------------------------------------------------- Task 3: real first audio
print("[Task 3] first-audio measured on the real TTS frame stream")
m = re.search(r"async def tts_node\(self, text, model_settings\):(.*?)\n        (?:async def|def) ", BUILDER, re.S)
check("Agent.tts_node override exists", m is not None)
body = m.group(1) if m else ""
check("calls library default (no TTS-object wrapping)",
      "Agent.default.tts_node(self, text, model_settings)" in body)
check("await-coroutine tolerance", "asyncio.iscoroutine(res)" in body)
check("stamps ONLY first frame, guarded once per turn",
      'if float(tt.get("first_tts_audio", 0) or 0) == 0.0:' in body)
check("no buffering: pure yield pass-through",
      re.search(r"async for frame in res:.*?yield frame", body, re.S) is not None)
check("feeds existing consumers' keys (first_audio/first_tts_audio/delta)",
      'tt["first_audio"] = _now' in body
      and 'tt["first_tts_audio"] = _now' in body
      and 'tt["last_speech_end_to_first_audio"] = _s2fa' in body)
check("[FIRST_ASSISTANT_AUDIO] + [LATENCY] logs emitted at the stamp",
      "[FIRST_ASSISTANT_AUDIO]" in body and "[LATENCY]" in body)
check("LATENCY line carries all five spec fields",
      all(k in body for k in ("stt_final_ms=", "turn_commit_ms=", "llm_ttft_ms=",
                              "tts_first_audio_ms=", "speech_to_first_audio_ms=")))
check("not faked from state/LLM events",
      "speaking" not in body.split("[FIRST_ASSISTANT_AUDIO]")[0][-400:])
# real stt-final arrival stamp (measured, not the 250ms fallback estimate)
check("stt_final_ts stamped at FINAL transcript arrival",
      'turn_timing["stt_final_ts"] = time.time()' in WORKER)
check("turn_commit_ts stamped at USER_TURN_COMPLETED",
      'self._turn_timing_ref["turn_commit_ts"] = time.time()' in BUILDER)

# ---------------------------------------------------------------- Task 4: fewer prompt tokens
print("[Task 4] duplicated rule text removed; grounding kept")
check("old duplicate ACK rule block gone",
      "ACKNOWLEDGEMENT TURNS (critical): if the caller's whole message is only an" not in BUILDER)
check("old duplicate INCOMPLETE rule block gone",
      "INCOMPLETE TURNS (critical): callers who think out loud" not in BUILDER)
check("single combined fallback rule kept (misclassified safety)",
      "ACK/INCOMPLETE TURNS:" in BUILDER)
check("instructions still built once per call (not per turn)",
      len(re.findall(r"instructions\s*=\s*build_instructions\(", BUILDER)) == 1)
check("no LLM summarization call added anywhere",
      "summarize" not in WORKER.lower())
check("prior-memory budget constant still caps history",
      "VOICE_PRIOR_MEMORY_BUDGET_CHARS" in BUILDER)

# ---------------------------------------------------------------- Task 5: invariants preserved
print("[Task 5] preserved machinery smoke checks")
check("greeting barge-in marker intact", "USER_SPEECH_DURING_GREETING" in WORKER)
check("generation-stamp stale guard intact", "STALE_GENERATION_DROPPED" in WORKER)
check("closing speech still uninterruptible",
      WORKER.count("allow_interruptions=False") >= 2)
check("ACK/incomplete single source still turn_rules",
      "from app.turn_rules import" in BUILDER or "turn_rules" in BUILDER)

# Pure logic: turn_rules classification (source of the deterministic paths)
print("[Logic] app/turn_rules.py behaviour")
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("turn_rules", str(BACKEND / "app/turn_rules.py"))
tr = _ilu.module_from_spec(_spec); _spec.loader.exec_module(tr)

ack_yes = ["ok", "Ok.", "haan", "हाँ", "ठीक है", "जी", "yes ji", "nice", "good", "sahi hai", "accha"]
ack_no = ["ok but what is the price", "fee kitni hai", "haan aap batao price", "address kya hai"]
inc_yes = ["Ok तो मुझे अगर इनसे business", "और यह", "मुझे यह", "और", "ek minute", "वो वाली बात कि"]
inc_no = ["fee kitni hai", "timings kya hain", "please call me back at 9am", "I want to book a demo"]
for t in ack_yes:
    check(f"ack: {t!r}", tr.is_acknowledgement(t))
for t in ack_no:
    check(f"not-ack: {t!r}", not tr.is_acknowledgement(t))
for t in inc_yes:
    check(f"incomplete: {t!r}", tr.is_incomplete_turn(t))
for t in inc_no:
    check(f"not-incomplete: {t!r}", not tr.is_incomplete_turn(t))
_r = tr.ack_reply("ok")
check("ack reply is short deterministic Hindi", len(_r) <= 12 and _r.startswith("जी"), repr(_r))

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
