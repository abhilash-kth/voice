"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import ProviderFormModal from "@/components/ProviderFormModal";
import {
  listProviders, updateProvider, deleteProvider,
  type Provider,
} from "@/lib/api";

const KINDS = ["llm", "stt", "tts", "telephony"] as const;

export default function ProvidersPage() {
  const [kind, setKind] = useState("llm");
  const [items, setItems] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const { busy, msg, err, run } = useBusy();

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listProviders(kind)
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [kind]);

  useEffect(load, [load]);

  const toggle = (p: Provider) =>
    run(() => updateProvider(p.id, { enabled: !p.enabled }), p.enabled ? "Provider disabled" : "Provider enabled ✓").then((ok) => {
      if (ok !== undefined) load();
    });

  const remove = (p: Provider) => {
    if (!window.confirm(`Delete provider "${p.slug}" (${p.kind})?`)) return;
    const cascade = window.confirm(
      "Also DELETE all catalog models belonging to this provider?\n\nOK = delete provider + its models\nCancel = delete provider only (fails if it still has models)"
    );
    run(() => deleteProvider(p.id, cascade), "Provider deleted ✓").then((ok) => {
      if (ok !== undefined) load();
    });
  };

  return (
    <>
      <PageHeader title="Providers" subtitle="Platform integrations — adapters, endpoints, availability">
        <button className="btn text-xs" onClick={() => setShowCreate(true)}>＋ Add provider</button>
      </PageHeader>

      {(msg || err) && (
        <div className={`mb-4 p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
          {msg || err}
        </div>
      )}

      <div className="card p-1.5 mb-4 inline-flex gap-1">
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`px-4 py-1.5 rounded-xl text-xs font-semibold uppercase tracking-wide transition-colors ${
              kind === k ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      <StateBox loading={loading} error={error} empty={items.length === 0 ? `No ${kind.toUpperCase()} providers yet.` : null}>
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Adapter</th>
                <th>Base URL</th>
                <th>Key env</th>
                <th>Tier</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div className="font-semibold text-gray-100">{p.display_name || p.slug}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{p.slug}</div>
                  </td>
                  <td className="text-gray-400 font-mono text-xs">{p.adapter || "—"}</td>
                  <td className="text-gray-400 font-mono text-xs max-w-52 truncate" title={p.base_url}>
                    {p.base_url || <span className="text-gray-600">default</span>}
                  </td>
                  <td className="text-gray-400 font-mono text-xs">{p.key_env || "—"}</td>
                  <td>
                    <span className={`pill ${p.tier === "free" ? "pill-blue" : "pill-amber"}`}>{p.tier}</span>
                  </td>
                  <td>
                    {p.enabled ? <span className="pill pill-green">● enabled</span> : <span className="pill pill-gray">○ disabled</span>}
                    {p.status === "deprecated" && <span className="pill pill-red ml-1">deprecated</span>}
                  </td>
                  <td>
                    <div className="flex gap-1.5">
                      <button className="btn-secondary text-xs px-2.5 py-1" disabled={busy} onClick={() => toggle(p)}>
                        {p.enabled ? "Disable" : "Enable"}
                      </button>
                      <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => setEditing(p)}>Edit</button>
                      <button className="btn-danger text-xs px-2.5 py-1" disabled={busy} onClick={() => remove(p)}>✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-600 mt-2">
          Disabled providers (and their models) disappear from the customer dashboard immediately — running calls are unaffected.
        </p>
      </StateBox>

      {showCreate && (
        <ProviderFormModal provider={null} defaultKind={kind} onClose={() => setShowCreate(false)} onSaved={load} />
      )}
      {editing && (
        <ProviderFormModal provider={editing} defaultKind={kind} onClose={() => setEditing(null)} onSaved={load} />
      )}
    </>
  );
}
