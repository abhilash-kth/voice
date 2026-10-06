"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import CredentialFormModal from "@/components/CredentialFormModal";
import {
  listCredentials, setCredentialStatus, listProviders, revealCredential, deleteCredential,
  type Credential, type Provider,
} from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

const STATUS_PILL: Record<string, string> = {
  active: "pill pill-green",
  disabled: "pill pill-gray",
  rotated: "pill pill-amber",
};

export default function ApiKeysPage() {
  const [items, setItems] = useState<Credential[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [kindFilter, setKindFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [rotating, setRotating] = useState<Credential | null>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const { busy, msg, err, run } = useBusy();

  const hideKey = (id: string) =>
    setRevealed((m) => {
      const n = { ...m };
      delete n[id];
      return n;
    });

  const toggleReveal = async (c: Credential) => {
    if (revealed[c.id]) {
      hideKey(c.id);
      return;
    }
    const r = await run(
      () => revealCredential(c.id),
      "Key revealed — shown only in this panel, recorded in the audit log"
    );
    if (r) setRevealed((m) => ({ ...m, [c.id]: r.value }));
  };

  const copyKey = (id: string) => {
    const v = revealed[id];
    if (v && typeof navigator !== "undefined") navigator.clipboard?.writeText(v).catch(() => {});
  };

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listCredentials(kindFilter ? { kind: kindFilter } : {})
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [kindFilter]);

  useEffect(load, [load]);
  useEffect(() => {
    listProviders().then((r) => setProviders(r.items)).catch(() => {});
  }, []);

  const setStatus = (c: Credential, status: "active" | "disabled") =>
    run(
      () => setCredentialStatus(c.id, status),
      status === "active" ? "Key re-enabled ✓" : "Key disabled — falls back to env var if set"
    ).then((ok) => {
      if (ok !== undefined) load();
    });

  const removeKey = async (c: Credential) => {
    const warn = c.status === "active"
      ? `Delete the ACTIVE key for ${c.provider_slug}? Calls will fall back to the provider's env-var key (if set). This is audited.`
      : `Delete this ${c.status} key for ${c.provider_slug}? This is audited.`;
    if (!window.confirm(warn)) return;
    hideKey(c.id);
    const ok = await run(() => deleteCredential(c.id), "Key deleted ✓");
    if (ok !== undefined) load();
  };

  return (
    <>
      <PageHeader
        title="API Keys"
        subtitle="One key per provider — a shared key serves all of that provider's services (LLM/STT/TTS). Encrypted at rest; reveals are audited."
      >
        <button className="btn text-xs" onClick={() => setShowCreate(true)}>＋ Add key</button>
      </PageHeader>

      {(msg || err) && (
        <div className={`mb-4 p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
          {msg || err}
        </div>
      )}

      <div className="card p-3 mb-4 flex items-center gap-2">
        <span className="text-xs text-gray-500">Filter:</span>
        {["", "llm", "stt", "tts", "telephony"].map((k) => (
          <button
            key={k}
            onClick={() => setKindFilter(k)}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors ${
              kindFilter === k ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            {k === "" ? "All" : k.toUpperCase()}
          </button>
        ))}
      </div>

      <StateBox
        loading={loading}
        error={error}
        empty={items.length === 0 ? "No keys stored. Calls fall back to the provider's env-var key (if set)." : null}
      >
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Label</th>
                <th>Key (masked)</th>
                <th>Status</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="font-semibold text-gray-100">{c.provider_slug}</span>
                    <span className="text-[11px] text-gray-500 ml-1.5">
                      [{c.kind ? c.kind.toUpperCase() : "SHARED"}]
                    </span>
                  </td>
                  <td className="text-gray-300">{c.label || <span className="text-gray-600">—</span>}</td>
                  <td className="font-mono text-xs text-gray-400 max-w-[260px]">
                    {revealed[c.id] ? (
                      <span className="text-emerald-300 break-all">{revealed[c.id]}</span>
                    ) : (
                      c.masked_value
                    )}
                  </td>
                  <td>
                    <span className={STATUS_PILL[c.status] || "pill pill-gray"}>● {c.status}</span>
                  </td>
                  <td className="text-gray-500 text-xs">{fmtDateTime(c.updated_at)}</td>
                  <td>
                    <div className="flex gap-1.5">
                      <button
                        className="btn-secondary text-xs px-2.5 py-1"
                        disabled={busy}
                        title={revealed[c.id] ? "Hide the plaintext key" : "Reveal the plaintext key (audited)"}
                        onClick={() => toggleReveal(c)}
                      >
                        {revealed[c.id] ? "Hide" : "👁 Reveal"}
                      </button>
                      {revealed[c.id] && (
                        <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => copyKey(c.id)}>Copy</button>
                      )}
                      <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => { hideKey(c.id); setRotating(c); }}>Rotate</button>
                      <button className="btn-danger text-xs px-2.5 py-1" disabled={busy} onClick={() => removeKey(c)}>
                        Delete
                      </button>
                      {c.status === "active" ? (
                        <button className="btn-danger text-xs px-2.5 py-1" disabled={busy} onClick={() => { hideKey(c.id); setStatus(c, "disabled"); }}>
                          Disable
                        </button>
                      ) : c.status === "disabled" ? (
                        <button className="btn-secondary text-xs px-2.5 py-1" disabled={busy} onClick={() => setStatus(c, "active")}>
                          Enable
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-600 mt-2">
          Keys are stored encrypted (Fernet) and used for calls in place of env-var keys. Reveal decrypts for this
          panel only, is written to the audit log, and the value is never logged server-side. Rotated keys are kept
          (masked) for audit.
        </p>
      </StateBox>

      {showCreate && (
        <CredentialFormModal
          mode="create"
          providers={providers}
          takenSlugs={items.filter((c) => c.status === "active").map((c) => c.provider_slug)}
          onClose={() => setShowCreate(false)}
          onSaved={load}
        />
      )}
      {rotating && (
        <CredentialFormModal mode="rotate" credential={rotating} providers={providers} onClose={() => setRotating(null)} onSaved={load} />
      )}
    </>
  );
}
