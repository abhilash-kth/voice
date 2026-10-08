"""ChatContext inspection for request-level LLM timing: message head
fingerprints (head_sha), token estimates + cache metadata. Extracted 1:1
from `w_llm_timing.py` (`LLMTimingWrapper.chat`).
"""
from __future__ import annotations

import hashlib as _hl
import logging
import time as _time

_logger = logging.getLogger("voice-agent-saas-worker")


def _inspect_chat_ctx(self, args, kwargs):
    _req_inflight = False
    _token_estimate_ns = _fingerprint_ns = _cache_metadata_ns = 0
    _cc = kwargs.get("chat_ctx")
    if _cc is None and args:
        _cc = args[0]
    _mf = getattr(_cc, "messages", None)
    # livekit-agents 1.8.2: ChatContext.messages is a METHOD
    # (returns list[ChatMessage]) — the previous direct getattr
    # produced a bound method, list() raised TypeError, and the
    # whole block died in a debug-level except: every production
    # request logged stable_head_chars=?/head_sha=?/inflight 0.
    _msgs = list(_mf() if callable(_mf) else (_mf or []))
    def _mtext(m):
        c = getattr(m, "content", "")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(getattr(p, "text", p)) for p in c)
        return str(c or "")
    _head: list = []
    _hist_chars = 0
    _hist_msgs = 0
    _rag_chars = 0
    _user_last_chars = 0
    _user_last_text = ""
    _dyn_before_head = 0
    _seen_user = False
    _user_last_is_final = False
    _first_sys = None
    for _i, _m in enumerate(_msgs):
        _r = getattr(_m, "role", "") or ""
        _t = _mtext(_m)
        _mid = getattr(_m, "id", "") or ""
        # Cache fix: ONLY the behavioral instructions (id=lk.agent_task.instructions)
        # are the stable cacheable prefix. All other system messages (prior_memory,
        # lead_data, RAG) are dynamic and must be counted as dynamic, not stable,
        # even if they appear before first user in older contexts. This makes the
        # logged stable_head reflect the TRUE provider-bound cacheable prefix.
        _is_stable = (_mid == "lk.agent_task.instructions") or (_r == "system" and _first_sys is None and not _seen_user and "[RAG]" not in _t[:80] and "Prior conversation" not in _t[:80] and "contact list" not in _t[:80].lower())
        # For first_sys detection, only stable instructions count as head start
        if _r == "system" and _first_sys is None and _is_stable:
            _first_sys = _i
        if _r == "system" and _is_stable and not _seen_user:
            _head.append(_t)
        elif _r == "system":
            _rag_chars += len(_t)
        else:
            _seen_user = True
            if _r == "user":
                # last USER message wherever it sits — the TEXT
                # feeds the continuation-merge. 11:41 fix: the
                # CHAR COUNT no longer requires the message to be
                # final (the old positional gate is what made
                # final_user=0c ambiguous between "question
                # missing" and "question present but not last").
                # Position is reported separately as question_is_last.
                _user_last_text = _t
                _user_last_chars = len(_t)
                _user_last_is_final = _i == len(_msgs) - 1
            else:
                _hist_chars += len(_t)
                _hist_msgs += 1
    _tools = kwargs.get("tools")
    if _tools is None and len(args) > 1:
        _tools = args[1]
    _tools = _tools or []
    _dyn_before_head = int(_first_sys or 0)
    # 03:07 K-exam fix: remember this request's question so the
    # builder can merge it into the caller's immediate
    # continuation if the request is superseded pre-output.
    self._timing["req_user_text"] = _user_last_text[:600]
    _token_estimate_start_ns = _time.perf_counter_ns()
    _tools_chars = sum(len(str(getattr(_t0, "name", _t0))) + len(str(getattr(_t0, "parameters", ""))) for _t0 in _tools)
    _head_chars = sum(len(_h) for _h in _head)
    _sha = _hl.sha256(("\x1f".join(_head) + "#tools=" + repr(_tools_chars)).encode("utf-8", "ignore")).hexdigest()[:12]
    _prev_sha = self._timing.get("head_sha") or ""
    _stable = "yes" if (not _prev_sha or _prev_sha == _sha) else "NO"
    self._timing["head_sha"] = _sha
    self._timing["head_sha_prev"] = _prev_sha
    self._timing["head_stable_prev"] = _stable
    self._timing["head_chars_log"] = _head_chars
    _head_est_t = int(_head_chars / 4.0)
    self._timing["head_est_tokens"] = _head_est_t
    _total_chars = _head_chars + _hist_chars + _rag_chars + _user_last_chars
    _dyn_rag_est_t = int(_rag_chars / 4.0)
    _total_est_t = int(_total_chars / 4.0)
    _token_estimate_ns = _time.perf_counter_ns() - _token_estimate_start_ns
    _logger.info(
        "\U0001f9ee [PROMPT] chars=%d est_total_tokens=%d tokens: stable_prompt=%d dynamic_rag=%d total_input_est=%d | sections: stable_head=%dc(~%dt) same_as_previous_turn=%s dynamic_prefix_before_stable_head=%d | history=%dc/%dmsg | rag_inject=%dc | final_user=%dc question_is_last=%s | tools_meta=%dc | head_sha=%s",
        _total_chars, _total_est_t, _head_est_t, _dyn_rag_est_t, _total_est_t, _head_chars, _head_est_t, _stable, _dyn_before_head, _hist_chars, _hist_msgs, _rag_chars, _user_last_chars, "yes" if _user_last_is_final else "NO", _tools_chars, _sha,
    )
    # 11:41 log Task 1: PROVE the request shape instead of
    # inferring it. The [PROMPT] section line cannot distinguish
    # "question present but not last" from "question missing"
    # without this; the preview shows the real last message, the
    # counts show how many user messages arrived, and ack_mode /
    # incomplete_turn echo the governor flags on the SHARED turn
    # dict (a deterministic-ack turn never reaches chat(), so
    # ack_mode=yes here would mean a stale flag hijacked a real
    # request — the one failure mode the pop-on-entry guards are
    # supposed to make impossible). 60-char previews only: no
    # full customer content, no secrets.
    _last_m = _msgs[-1] if _msgs else None
    _dbg_prov = self._prov_info.get("provider", "") or self._timing.get("llm_provider", "") or "unknown"
    _dbg_model = self._prov_info.get("model_id", "") or getattr(self._inner, "model", "unknown") or "unknown"
    _cache_metadata_start_ns = _time.perf_counter_ns()
    try:
        from app.llm_catalog import get_prompt_cache_capability as _gcc_dbg
        _dbg_cap = _gcc_dbg(str(_dbg_prov), str(_dbg_model)).get("mode", "?")
    except Exception:
        _dbg_cap = "?"
    _cache_metadata_ns = _time.perf_counter_ns() - _cache_metadata_start_ns
    _logger.info(
        "\U0001f52c [LLM_INPUT_DEBUG] generation=%s provider=%s model=%s capability=%s messages_count=%d last_message_role=%s last_message_preview='%s' current_user_turn='%s' user_messages=%d question_is_last=%s rag_present=%s rag_chars=%d ack_mode=%s incomplete_turn=%s",
        _gen, _dbg_prov, _dbg_model, _dbg_cap, len(_msgs),
        str(getattr(_last_m, "role", "?") or "?") if _last_m is not None else "?",
        (_mtext(_last_m)[:60].replace("\n", " ") if _last_m is not None else ""),
        _user_last_text[:60].replace("\n", " "),
        sum(1 for _m2 in _msgs if getattr(_m2, "role", "") == "user"),
        "yes" if _user_last_is_final else "NO",
        "yes" if _rag_chars else "no", _rag_chars,
        "yes" if self._timing.get("ack_reply") else "no",
        "yes" if self._timing.get("gov_turn_state") == "suppress" else "no",
    )
    # --- Provider-bound fingerprint for cache diagnosis (safe, no PII) ---
    # Latency fix: avoid duplicate ChatContext -> provider format
    # serialization on the event loop (to_provider_format does a
    # full copy/transform of ~10k chars). Use the already-parsed
    # _msgs list directly — same data, zero extra serialization.
    # No cache logic changed, only diagnostic path.
    _fingerprint_start_ns = _time.perf_counter_ns()
    try:
        _prov_msgs = _msgs  # use existing parsed messages, not to_provider_format
        _prov_role_seq = "?"
        _prov_len_seq = "?"
        _prov_first_hash = "?"
        _prov_prefix_hash = "?"
        _prov_prefix_same = "?"
        if _prov_msgs:
            _prov_role_seq = ",".join([str(getattr(m, "role", "?")) for m in _prov_msgs])
            _prov_len_seq = ",".join([str(len(_mtext(m))) for m in _prov_msgs])
            _first_c = _mtext(_prov_msgs[0]) if _prov_msgs else ""
            _prov_first_hash = _hl.sha256(_first_c.encode("utf-8", "ignore")).hexdigest()[:12] if _first_c else "?"
            _pref_c = "".join([_mtext(m) for m in _prov_msgs[:2]])
            _prov_prefix_hash = _hl.sha256(_pref_c.encode("utf-8", "ignore")).hexdigest()[:12] if _pref_c else "?"
            _prev_pref = self._timing.get("prov_prefix_hash", "")
            _prov_prefix_same = "yes" if (not _prev_pref or _prev_pref == _prov_prefix_hash) else "NO"
            self._timing["prov_prefix_hash"] = _prov_prefix_hash
            self._timing["prov_prefix_hash_prev"] = _prev_pref
        _pck = getattr(getattr(self._inner, "_opts", None), "prompt_cache_key", None) or getattr(self._inner, "prompt_cache_key", None) or "?"
        # Never log full content, only hashes/lengths/roles
        # Cache diagnostics: show stable_head size to prove >1024 eligibility
        _stable_chars_log = self._timing.get("head_chars_log", "?")
        _stable_tokens_log = self._timing.get("head_est_tokens", "?")
        _logger.info(
            "\U0001f50d [PROVIDER_BOUND] provider=%s model=%s prompt_cache_key=%s prov_messages=%d role_seq=%s len_seq=%s first_hash=%s prefix_hash=%s prefix_same_as_previous=%s app_head_sha=%s app_head_same=%s stable_head_chars=%s stable_head_tokens_est=%s",
            _dbg_prov, _dbg_model, _pck, len(_prov_msgs), _prov_role_seq, _prov_len_seq, _prov_first_hash, _prov_prefix_hash, _prov_prefix_same, _sha, _stable, _stable_chars_log, _stable_tokens_log,
        )
    except Exception as _pb_e:
        _logger.debug(f"[PROVIDER_BOUND] fingerprint failed: {_pb_e!r}")
    finally:
        _fingerprint_ns = _time.perf_counter_ns() - _fingerprint_start_ns
    # inflight gauge for spike forensics (Task 5)
    self._timing["inflight_llm"] = int(self._timing.get("inflight_llm", 0)) + 1
    # Per-request ownership (12:28): this used to be the shared
    # "_inflight_counted" flag — with two overlapping streams
    # (fallback switch / barge-in) whichever finished first
    # consumed the flag and the OTHER skipped its own decrement,
    # pinning llm_active=True. The counter is owned by THIS
    # request now and travels on the CM/stream objects.
    _req_inflight = True
    return (_token_estimate_ns, _fingerprint_ns, _cache_metadata_ns, _req_inflight)
