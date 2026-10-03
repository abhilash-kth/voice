"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import CredentialFormModal from "@/components/CredentialFormModal";
import {
  listCredentials, setCredentialStatus, listProviders,
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
  const { busy, msg, err, run } = useBusy();

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

  return (
    <>
      <PageHeader title="API Keys" subtitle="Provider credentials — encrypted at rest, write-only, always shown masked">
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
                    <span className="text-[11px] text-gray-500 ml-1.5">[{c.kind.toUpperCase()}]</span>
                  </td>
                  <td className="text-gray-300">{c.label || <span className="text-gray-600">—</span>}</td>
                  <td className="font-mono text-xs text-gray-400">{c.masked_value}</td>
                  <td>
                    <span className={STATUS_PILL[c.status] || "pill pill-gray"}>● {c.status}</span>
                  </td>
                  <td className="text-gray-500 text-xs">{fmtDateTime(c.updated_at)}</td>
                  <td>
                    <div className="flex gap-1.5">
                      <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => setRotating(c)}>Rotate</button>
                      {c.status === "active" ? (
                        <button className="btn-danger text-xs px-2.5 py-1" disabled={busy} onClick={() => setStatus(c, "disabled")}>
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
          Plaintext keys are never stored readable and never leave the server in any response. Rotated keys are kept (masked) for audit.
        </p>
      </StateBox>

      {showCreate && (
        <CredentialFormModal mode="create" providers={providers} onClose={() => setShowCreate(false)} onSaved={load} />
      )}
      {rotating && (
        <CredentialFormModal mode="rotate" credential={rotating} providers={providers} onClose={() => setRotating(null)} onSaved={load} />
      )}
    </>
  );
}
