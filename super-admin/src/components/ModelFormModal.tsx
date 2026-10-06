"use client";
import { useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import { createModel, updateModel, listProviders, type CatalogModel, type Provider } from "@/lib/api";
import { toNum } from "@/lib/format";

// Price fields per kind (other kinds' price inputs are hidden to keep the
// form focused — they can still be edited later via the API).
const PRICE_FIELDS: Record<string, { key: keyof CatalogModel; label: string }[]> = {
  llm: [
    { key: "input_price_per_1m", label: "Input ₹ / 1M tokens" },
    { key: "cached_input_price_per_1m", label: "Cached input ₹ / 1M" },
    { key: "output_price_per_1m", label: "Output ₹ / 1M tokens" },
  ],
  tts: [{ key: "cost_per_1k_chars", label: "Cost ₹ / 1K chars" }],
  stt: [{ key: "cost_per_min", label: "Cost ₹ / min" }],
};

export default function ModelFormModal({
  model,
  defaultKind,
  onClose,
  onSaved,
}: {
  model: CatalogModel | null;      // null = create mode
  defaultKind: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const edit = model !== null;
  const [kind, setKind] = useState(edit ? model.kind : defaultKind);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerId, setProviderId] = useState(edit ? model.provider_id : "");
  const [catalogId, setCatalogId] = useState(edit ? model.catalog_id : "");
  const [modelId, setModelId] = useState(edit ? model.model_id : "");
  const [displayName, setDisplayName] = useState(edit ? model.display_name : "");
  const [tier, setTier] = useState(edit ? model.tier : "paid");
  const [priceMin, setPriceMin] = useState(edit ? String(model.customer_price_per_min) : "0");
  const [prices, setPrices] = useState<Record<string, string>>(() => {
    if (!edit) return {};
    const out: Record<string, string> = {};
    for (const f of PRICE_FIELDS[model.kind] || []) out[f.key] = String(model[f.key] ?? 0);
    return out;
  });
  // Per-TTS-model voice-speed bounds for the customer slider (stored in meta).
  // Empty = use the global Billing config range.
  const meta = (edit ? (model.meta || {}) : {}) as Record<string, unknown>;
  const sMeta = (k: string) => {
    const v = edit && model.kind === "tts" ? meta[k] : undefined;
    return v === null || v === undefined ? "" : String(v);
  };
  const [speedMin, setSpeedMin] = useState(sMeta("speed_min"));
  const [speedMax, setSpeedMax] = useState(sMeta("speed_max"));
  const [speedDefault, setSpeedDefault] = useState(sMeta("speed_default"));
  const { busy, err, run } = useBusy();

  useEffect(() => {
    listProviders(kind).then((r) => setProviders(r.items)).catch(() => setProviders([]));
  }, [kind]);

  const submit = () => {
    const patch: Partial<CatalogModel> = {
      display_name: displayName.trim(),
      tier,
      customer_price_per_min: toNum(priceMin),
    };
    for (const f of PRICE_FIELDS[kind] || []) {
      (patch as Record<string, unknown>)[f.key] = toNum(prices[f.key] ?? "0");
    }
    if (kind === "tts") {
      // Empty field = no per-model bound (falls back to the global Billing range).
      // null REMOVES a previously set bound (server merges meta keys).
      const mk = (s: string) => (s.trim() === "" ? null : toNum(s));
      patch.meta = {
        speed_min: mk(speedMin),
        speed_max: mk(speedMax),
        speed_default: mk(speedDefault),
      } as Record<string, unknown>;
    }
    run(async () => {
      if (edit) {
        await updateModel(model.id, patch);
      } else {
        await createModel({
          kind, provider_id: providerId,
          catalog_id: catalogId.trim(), model_id: modelId.trim(),
          ...patch,
        });
      }
      onSaved();
    }, edit ? "Model updated ✓" : "Model created ✓").then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit = edit
    ? displayName.trim().length > 0
    : providerId && catalogId.trim().length > 0;

  return (
    <Modal title={edit ? `Edit model — ${model.display_name}` : "Add catalog model"} onClose={onClose}>
      <div className="space-y-3 text-sm">
        {err && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">⚠ {err}</div>
        )}

        {!edit && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Kind</span>
                <select className="input mt-1" value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="llm">LLM</option>
                  <option value="stt">STT</option>
                  <option value="tts">TTS</option>
                  <option value="telephony">Telephony</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Provider</span>
                <select className="input mt-1" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                  <option value="">Select…</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>{p.slug}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-xs text-gray-400 font-medium">Catalog ID (unique, e.g. gpt-4o-mini)</span>
              <input className="input mt-1" value={catalogId} onChange={(e) => setCatalogId(e.target.value)} placeholder="provider-model-id" />
            </label>
            <label className="block">
              <span className="text-xs text-gray-400 font-medium">Model ID (sent to provider API)</span>
              <input className="input mt-1" value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="defaults to catalog ID" />
            </label>
          </>
        )}

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Display name</span>
            <input className="input mt-1" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Tier</span>
            <select className="input mt-1" value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="free">free</option>
              <option value="paid">paid</option>
            </select>
          </label>
        </div>

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Customer price ₹ / min (voice; what USERS are billed)</span>
          <input className="input mt-1" type="number" step="0.01" min="0" value={priceMin} onChange={(e) => setPriceMin(e.target.value)} />
        </label>

        {(PRICE_FIELDS[kind] || []).map((f) => (
          <label className="block" key={f.key}>
            <span className="text-xs text-gray-400 font-medium">{f.label} (provider COST — never shown to users)</span>
            <input
              className="input mt-1" type="number" step="0.000001" min="0"
              value={prices[f.key] ?? "0"}
              onChange={(e) => setPrices((p) => ({ ...p, [f.key]: e.target.value }))}
            />
          </label>
        ))}

        {kind === "tts" && (
          <div className="rounded-xl border border-gray-800 p-3 space-y-2">
            <span className="text-xs text-gray-300 font-semibold">
              Voice-speed range for THIS model (customer slider)
            </span>
            <p className="text-[10px] text-gray-600">
              Different voices support different speeds. Leave empty to use the global
              Billing-config range. Overrides min/max/default shown to customers who pick this model.
            </p>
            <div className="grid grid-cols-3 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Min ×</span>
                <input className="input mt-1" type="number" step="0.05" min="0.1" value={speedMin} onChange={(e) => setSpeedMin(e.target.value)} placeholder="—" />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Max ×</span>
                <input className="input mt-1" type="number" step="0.05" min="0.1" value={speedMax} onChange={(e) => setSpeedMax(e.target.value)} placeholder="—" />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 font-medium">Default ×</span>
                <input className="input mt-1" type="number" step="0.05" min="0.1" value={speedDefault} onChange={(e) => setSpeedDefault(e.target.value)} placeholder="—" />
              </label>
            </div>
          </div>
        )}

        <p className="text-[10px] text-gray-600">
          New models are created DISABLED — flip them on from the table after verifying prices.
          Cost fields are internal and used for profit reporting only.
        </p>

        <div className="flex justify-end gap-2 pt-1">
          <button className="btn-secondary text-xs" onClick={onClose}>Cancel</button>
          <button className="btn text-xs" disabled={busy || !canSubmit} onClick={submit}>
            {busy ? "Saving…" : edit ? "Save changes" : "Create model"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
