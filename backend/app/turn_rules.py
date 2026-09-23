"""Turn classification rules shared by the worker and the agent builder.

Pure text heuristics — no imports beyond stdlib, safe to call on every STT
event (microseconds, no I/O, no model). Both consumers must agree on the same
rules, so this is the single source of truth:

* ``is_acknowledgement`` — turn is nothing but filler ("Ok.", "ठीक है").
  The builder hook turns these into a DETERMINISTIC reply via the agent's
  ``llm_node`` override: no RAG, no LLM request, no billing (2026-09-24 log:
  'Ok.' still burned a 2865-token request, and its intended 3-char answer
  'जी।' was then mis-flagged by the fallback heuristic and the caller heard
  an apology instead).
* ``is_incomplete_turn`` — strong linguistic evidence the caller is still
  composing ("...के लिए अगर", trailing conjunctions, "एक minute"). The hook
  marks the turn suppressed (llm_node returns nothing) and keeps the fragment
  to MERGE into the next completed turn, instead of firing one LLM request
  per fragment (2026-09-24 log: one thought split into 4 finals produced 3
  invalidated 0/0 requests + 1 answered).

Both must stay conservative: a misfire either silences the agent (incomplete
false-positive) or spends one cheap canned line (ack false-positive).
"""
from __future__ import annotations

import re

_WORD_SPLIT = re.compile(r"[^\wऀ-ॿ']+", flags=re.UNICODE)

# Words that are pure acknowledgement/filler — a turn made ONLY of these is
# not a question. Deliberately excludes anything with information content:
# "bye"/"alvida" (handled by the closing guard), "chalo", "number", "price".
_ACK_WORDS = {
    # latin
    "ok", "okay", "okey", "kk", "k", "thx", "thanks", "thank", "nice",
    "good", "great", "yes", "yeah", "yep", "yup", "sure", "fine", "right",
    "cool", "wow", "hmm", "hm", "ha", "haa", "haan", "han", "ji", "sir",
    "madam", "mam", "maam", "theek", "thik", "accha", "achha", "achcha",
    "sahi", "hai", "ha",
    # devanagari
    "ठीक", "है", "जी", "हा", "हां", "हाँ", "अच्छा", "अच्छी", "सही", "शाबाश",
    "ठिक", "थीक",
}


def _norm_words(text: str) -> list[str]:
    t = (text or "").strip().lower()
    if not t:
        return []
    return [w for w in _WORD_SPLIT.split(t) if w]


def is_acknowledgement(text: str) -> bool:
    """True when the whole turn is only acknowledgement/filler words.

    Guards: any '?' (so "haan to?" stays a question) or any word carrying
    content disqualifies; max 3 words. Used to skip per-turn RAG retrieval/
    injection and to route the turn to the deterministic llm_node reply.
    """
    try:
        if "?" in text or "？" in text or "¿" in text:
            return False
        words = _norm_words(text)
        if not words or len(words) > 3:
            return False
        return all(w in _ACK_WORDS for w in words)
    except Exception:
        return False


def ack_reply(text: str) -> str:
    """Deterministic spoken reply for an acknowledgement turn (spec 2026-09-24)."""
    try:
        words = _norm_words(text)
    except Exception:
        words = []
    if any(w in ("haan", "हाँ", "हां", "हा", "han", "ha", "haa") for w in words):
        # caller affirms and probably wants to continue / expects the floor back
        return "जी, बताइए।"
    return "जी।"


# Strong continuation evidence — a turn ENDING with one of these is almost
# certainly cut mid-thought (Hindi postpositions/conjunctions/interrogatives
# + English equivalents). Kept small on purpose; these override even a
# present terminal verb ("मैं आ रहा हूं और..." continues).
_HARD_TRAILING = {
    "और", "लेकिन", "परंतु", "क्योंकि", "अगर", "यदि", "कि", "तो", "का", "की",
    "के", "को", "से", "में", "मे", "पर", "लिए", "वाला", "वाली", "वाले", "जो",
    "जब", "तब", "तक", "जितना", "क्या", "कौन", "कैसे", "कब", "कहां", "कहाँ",
    "कितना", "कितनी", "क्यों", "चाहिए tha",  # (typo-guard, never matches)
    "and", "but", "because", "if", "so", "that", "this", "these", "those",
    "for", "of", "with", "in", "on", "at", "to", "my", "your", "our", "their",
    "is", "are", "am", "can", "would", "should", "want", "need", "like",
}

# Personal/dative pronouns: weak evidence alone — only incomplete when NO
# terminal verb is present ("Ok तो मुझे अगर इनसे business" vs "मुझे CRM चाहिए").
_SOFT_TRAILING = {
    "मुझे", "हमें", "तुम्हें", "तुमको", "आपको", "मेरा", "मेरी", "मेरे",
    "आपका", "आपकी", "अपना", "अपनी", "इनका", "उनका", "इसका", "इसके",
    "उसके", "हमारा", "हमारी", "those",
}

# Verb/copula endings that make a Hindi/Hinglish clause finishable.
_TERMINAL_VERBS = {
    "है", "हैं", "था", "थी", "थे", "होगा", "होंगे", "होगी", "होती", "होता",
    "चाहिए", "सकता", "सकती", "सकते", "रहा", "रही", "रहे", "दें", "दीजिए",
    "बताओ", "बताइए", "बताएँ", "करना", "करता", "करती", "बनवाना", "जानना",
    "पूछना", "आना", "चाहता", "चाहती", "रखें", "रखो", "मिलता", "मिलती",
    "किया", "करूं", "करूँ", "हो", "हूँ", "हूं",
}

# "hold on" family: never answer, just wait.
_WAIT_RE = re.compile(
    r"^(?:एक|ek|one)\s?(?:मिनट|minute|min|सेकंड|second|sec|पल|moment)[.!]?$"
    r"|^(?:रुकिए|रुक जाओ|रुको|hold\s?on|wait|wait a sec|one sec)\b[.!]?$",
    re.IGNORECASE,
)

# Conditionals that combine with a dangling मुझे/हमें into clear incompleteness.
_CONDITION_WORDS = {"अगर", "यदि", "कि", "के", "लिए", "if", "whether"}
_DANGLING_BENEFICIARY = {"मुझे", "हमें", "तुम्हें", "आपको", "want", "need"}


def is_incomplete_turn(text: str) -> bool:
    """True only on STRONG evidence the utterance continues.

    Never applies to questions ('?'), never to >16 words, never to a turn with
    a terminal verb unless it ends in a hard conjunction. Complete short
    answers ("मुझे CRM चाहिए", "product बनवाना है") pass through untouched.
    """
    try:
        t = (text or "").strip()
        if not t:
            return False
        if "?" in t or "？" in t:
            return False
        if t.endswith("।") or t.endswith("!"):
            return False
        words = _norm_words(t)
        if not words or len(words) > 16:
            return False
        if _WAIT_RE.match(t):
            return True
        last = words[-1]
        if last in _HARD_TRAILING:
            return True
        has_verb = any(w in _TERMINAL_VERBS for w in words)
        if last in _SOFT_TRAILING and not has_verb:
            return True
        # "Ok तो मुझे अगर इनसे business": dangling beneficiary + conditional +
        # no verb of any kind => the request was never completed.
        if (
            not has_verb
            and len(words) <= 12
            and any(w in _DANGLING_BENEFICIARY for w in words)
            and any(w in _CONDITION_WORDS for w in words)
        ):
            return True
        # Bare demonstrative endings while still talking ("और यह कहां पर अब")
        # — only when the clause has no verb at all and is very short.
        if (
            not has_verb
            and len(words) <= 5
            and last in {"यह", "यहां", "वह", "this", "that"}
        ):
            return True
        return False
    except Exception:
        return False
