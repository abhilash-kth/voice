"use client";
import { useEffect, useState } from "react";
import { AlertCircle, Info, Loader2, Save, Plus } from "lucide-react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import {
  createModel,
  updateModel,
  listProviders,
  type CatalogModel,
  type Provider,
} from "@/lib/api";
import { toNum } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

interface PriceField {
  key: keyof CatalogModel;
  label: string;
}

// Price fields per kind (other kinds' price inputs are hidden to keep the
// form focused — they can still be edited later via the API).
const PRICE_FIELDS: Record<string, PriceField[]> = {
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
  model: CatalogModel | null; // null = create mode
  defaultKind: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const edit = model !== null;
  const [kind, setKind] = useState<string>(edit ? model.kind : defaultKind);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerId, setProviderId] = useState<string>(
    edit ? model.provider_id : "",
  );
  const [catalogId, setCatalogId] = useState<string>(
    edit ? model.catalog_id : "",
  );
  const [modelId, setModelId] = useState<string>(edit ? model.model_id : "");
  const [displayName, setDisplayName] = useState<string>(
    edit ? model.display_name : "",
  );
  const [tier, setTier] = useState<string>(edit ? model.tier : "paid");
  const [priceMin, setPriceMin] = useState<string>(
    edit ? String(model.customer_price_per_min) : "0",
  );
  const [prices, setPrices] = useState<Record<string, string>>(() => {
    if (!edit || !model) return {};
    const out: Record<string, string> = {};
    const fields = PRICE_FIELDS[model.kind] || [];
    for (const f of fields) {
      const val = model[f.key];
      out[String(f.key)] =
        val !== undefined && val !== null ? String(val) : "0";
    }
    return out;
  });
  const { busy, err, run } = useBusy();

  useEffect(() => {
    listProviders(kind)
      .then((r) => setProviders(r.items))
      .catch(() => setProviders([]));
  }, [kind]);

  const submit = () => {
    const patch: Partial<CatalogModel> = {
      display_name: displayName.trim(),
      tier,
      customer_price_per_min: toNum(priceMin),
    };
    const fields = PRICE_FIELDS[kind] || [];
    for (const f of fields) {
      (patch as Record<string, unknown>)[String(f.key)] = toNum(
        prices[String(f.key)] ?? "0",
      );
    }
    run(
      async () => {
        if (edit && model) {
          await updateModel(model.id, patch);
        } else {
          await createModel({
            kind,
            provider_id: providerId,
            catalog_id: catalogId.trim(),
            model_id: modelId.trim(),
            ...patch,
          });
        }
        onSaved();
      },
      edit ? "Model updated ✓" : "Model created ✓",
    ).then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit = edit
    ? displayName.trim().length > 0
    : Boolean(providerId && catalogId.trim().length > 0);

  const activePriceFields = PRICE_FIELDS[kind] || [];

  return (
    <Modal
      title={
        edit && model
          ? `Edit model — ${model.display_name}`
          : "Add catalog model"
      }
      onClose={onClose}
    >
      <div className="space-y-5 text-sm">
        {err && (
          <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/5 px-3.5 py-3 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="leading-relaxed">{err}</span>
          </div>
        )}

        {!edit && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-muted-foreground">
                  Kind
                </Label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="llm">LLM</option>
                  <option value="stt">STT</option>
                  <option value="tts">TTS</option>
                  <option value="telephony">Telephony</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-muted-foreground">
                  Provider
                </Label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={providerId}
                  onChange={(e) => setProviderId(e.target.value)}
                >
                  <option value="">Select…</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.slug}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">
                Catalog ID{" "}
                <span className="font-normal text-muted-foreground/70">
                  (unique, e.g. gpt-4o-mini)
                </span>
              </Label>
              <Input
                className="h-9 font-mono text-sm"
                value={catalogId}
                onChange={(e) => setCatalogId(e.target.value)}
                placeholder="provider-model-id"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">
                Model ID{" "}
                <span className="font-normal text-muted-foreground/70">
                  (sent to provider API)
                </span>
              </Label>
              <Input
                className="h-9 font-mono text-sm"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                placeholder="defaults to catalog ID"
              />
            </div>

            <Separator />
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Display name
            </Label>
            <Input
              className="h-9"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Tier
            </Label>
            <select
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
            >
              <option value="free">free</option>
              <option value="paid">paid</option>
            </select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Customer price ₹ / min{" "}
            <span className="font-normal text-muted-foreground/70">
              (voice — what users are billed)
            </span>
          </Label>
          <Input
            className="h-9 tabular-nums"
            type="number"
            step="0.01"
            min="0"
            value={priceMin}
            onChange={(e) => setPriceMin(e.target.value)}
          />
        </div>

        {activePriceFields.length > 0 && (
          <div className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Provider cost
              <span className="ml-1.5 font-normal normal-case tracking-normal text-muted-foreground/70">
                — internal only, never shown to users
              </span>
            </p>
            <div className="space-y-3">
              {activePriceFields.map((f) => {
                const keyStr = String(f.key);
                return (
                  <div className="space-y-1.5" key={keyStr}>
                    <Label className="text-xs font-medium text-muted-foreground">
                      {f.label}
                    </Label>
                    <Input
                      className="h-9 tabular-nums"
                      type="number"
                      step="0.000001"
                      min="0"
                      value={prices[keyStr] ?? "0"}
                      onChange={(e) =>
                        setPrices((p) => ({ ...p, [keyStr]: e.target.value }))
                      }
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex items-start gap-2.5 rounded-lg border border-border/50 bg-muted/20 px-3.5 py-3">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            New models are created DISABLED — flip them on from the table after
            verifying prices. Cost fields are internal and used for profit
            reporting only.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" disabled={busy || !canSubmit} onClick={submit}>
            {busy ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Saving…
              </>
            ) : edit ? (
              <>
                <Save className="mr-2 h-3.5 w-3.5" />
                Save changes
              </>
            ) : (
              <>
                <Plus className="mr-2 h-3.5 w-3.5" />
                Create model
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
