"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox, useBusy } from "@/components/PageHeader";
import Pager from "@/components/Pager";
import ModelFormModal from "@/components/ModelFormModal";
import {
  listModels, updateModel, deleteModel,
  type CatalogModel, type Paged,
} from "@/lib/api";
import { fmtINR } from "@/lib/format";

const KINDS = ["llm", "stt", "tts", "telephony"] as const;

export default function ModelsPage() {
  const [kind, setKind] = useState("llm");
  const [data, setData] = useState<Paged<CatalogModel> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<CatalogModel | null>(null);
  const { busy, msg, err, run } = useBusy();

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listModels({ kind, page, page_size: 50 })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [kind, page]);

  useEffect(load, [load]);

  const toggle = (m: CatalogModel) =>
    run(() => updateModel(m.id, { enabled: !m.enabled }), m.enabled ? "Model disabled" : "Model enabled ✓").then((ok) => {
      if (ok !== undefined) load();
    });

  const remove = (m: CatalogModel) => {
    if (!window.confirm(`Delete model "${m.display_name}" (${m.catalog_id})?\n\nAgents currently using it will fall back to their configured fallback.`)) return;
    run(() => deleteModel(m.id), "Model deleted ✓").then((ok) => {
      if (ok !== undefined) load();
    });
  };

  return (
    <>
      <PageHeader title="Catalog models" subtitle="What customers can pick per agent — pricing, tiers, availability">
        <button className="btn text-xs" onClick={() => setShowCreate(true)}>＋ Add model</button>
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
            onClick={() => { setKind(k); setPage(1); }}
            className={`px-4 py-1.5 rounded-xl text-xs font-semibold uppercase tracking-wide transition-colors ${
              kind === k ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      <StateBox loading={loading} error={error} empty={data && data.items.length === 0 ? `No ${kind.toUpperCase()} models yet.` : null}>
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Provider</th>
                <th>Tier</th>
                <th className="text-right">Customer ₹/min</th>
                <th className="text-right">Cost</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((m) => (
                <tr key={m.id}>
                  <td>
                    <div className="font-semibold text-gray-100">{m.display_name}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{m.catalog_id}{m.model_id && m.model_id !== m.catalog_id ? ` → ${m.model_id}` : ""}</div>
                  </td>
                  <td className="text-gray-400">{m.provider_slug}</td>
                  <td>
                    <span className={`pill ${m.tier === "free" ? "pill-blue" : "pill-amber"}`}>{m.tier}</span>
                  </td>
                  <td className="text-right font-semibold text-emerald-300">{fmtINR(m.customer_price_per_min)}</td>
                  <td className="text-right text-gray-400 text-xs">
                    {m.kind === "llm"
                      ? `₹${m.input_price_per_1m}/₹${m.output_price_per_1m} per 1M`
                      : m.kind === "tts"
                        ? `₹${m.cost_per_1k_chars}/1K chars`
                        : `₹${m.cost_per_min}/min`}
                  </td>
                  <td>
                    {m.enabled ? <span className="pill pill-green">● live</span> : <span className="pill pill-gray">○ hidden</span>}
                  </td>
                  <td>
                    <div className="flex gap-1.5">
                      <button className="btn-secondary text-xs px-2.5 py-1" disabled={busy} onClick={() => toggle(m)}>
                        {m.enabled ? "Disable" : "Enable"}
                      </button>
                      <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => setEditing(m)}>Edit</button>
                      <button className="btn-danger text-xs px-2.5 py-1" disabled={busy} onClick={() => remove(m)}>✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && <Pager total={data.total} page={data.page} pageSize={data.page_size} onPage={setPage} />}
        <p className="text-[10px] text-gray-600 mt-2">
          Hidden models are not shown to customers. Customer ₹/min is what users are billed; Cost is what the provider charges you (internal only).
        </p>
      </StateBox>

      {showCreate && (
        <ModelFormModal model={null} defaultKind={kind} onClose={() => setShowCreate(false)} onSaved={load} />
      )}
      {editing && (
        <ModelFormModal model={editing} defaultKind={kind} onClose={() => setEditing(null)} onSaved={load} />
      )}
    </>
  );
}
