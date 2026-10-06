"use client";

// Super Admin → Billing: per-mode flat pricing + concurrency tiers + misc fee.
// Values are string states owned by the billing page (kept small & controlled).

export interface ModePricingState {
  announcement: string;  // ₹/min flat rate; "0" = use per-model prices
  assistant: string;     // ₹/min flat rate; "0" = use per-model prices
  misc: string;          // ₹/min added to every billed call
  tiers: { up_to: string; addon: string }[];  // concurrency surcharges
}

export function ModePricingCard({
  value,
  onChange,
}: {
  value: ModePricingState;
  onChange: (v: ModePricingState) => void;
}) {
  const set = (patch: Partial<ModePricingState>) => onChange({ ...value, ...patch });
  const setTier = (i: number, patch: Partial<{ up_to: string; addon: string }>) =>
    set({ tiers: value.tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)) });

  return (
    <div className="card p-5 space-y-4">
      <h2 className="text-sm font-bold">Customer rate card — flat overrides, surcharges &amp; misc</h2>
      <p className="text-xs text-gray-500 leading-relaxed">
        What the customer pays per minute = <b className="text-gray-300">model prices</b> (set per LLM/STT/TTS
        on the Models page) + <b className="text-gray-300">concurrency surcharge</b> + <b className="text-gray-300">misc fee</b>.
        A flat mode rate below <b className="text-gray-300">replaces the model prices</b> for that mode (never the surcharges).
      </p>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Announcement flat ₹ / min" hint="Replaces model prices for announcement-mode calls. 0 = use model prices.">
          <input className="input" type="number" step="0.01" min="0" value={value.announcement}
                 onChange={(e) => set({ announcement: e.target.value })} />
        </Field>
        <Field label="Assistant flat ₹ / min" hint="Replaces model prices for assistant-mode calls. 0 = use model prices.">
          <input className="input" type="number" step="0.01" min="0" value={value.assistant}
                 onChange={(e) => set({ assistant: e.target.value })} />
        </Field>
        <Field label="Misc fee ₹ / min" hint="Always added on top of everything for every billed call.">
          <input className="input" type="number" step="0.01" min="0" value={value.misc}
                 onChange={(e) => set({ misc: e.target.value })} />
        </Field>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400 font-medium">Concurrency surcharges (₹ / min)</span>
          <button
            className="btn-secondary text-xs px-2.5 py-1"
            onClick={() => set({ tiers: [...value.tiers, { up_to: "", addon: "" }] })}
          >＋ Add tier</button>
        </div>
        <p className="text-[10px] text-gray-600 mt-1">
          Tiers must ascend by &ldquo;up to&rdquo;. Example: up to 5 → +₹0.50, up to 10 → +₹1.00: an agent set to
          Max concurrent 3 pays +₹0.50/min, one set to 8 pays +₹1.00/min.
        </p>
        {value.tiers.length === 0 && (
          <p className="text-xs text-gray-500 mt-2">No surcharges — concurrency is not billed.</p>
        )}
        <div className="space-y-2 mt-2">
          {value.tiers.map((t, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-xs text-gray-500">up to</span>
              <input className="input w-24" type="number" min="1" value={t.up_to}
                     onChange={(e) => setTier(i, { up_to: e.target.value })} placeholder="5" />
              <span className="text-xs text-gray-500">concurrent →</span>
              <span className="text-xs text-gray-500">+₹</span>
              <input className="input w-28" type="number" step="0.01" min="0" value={t.addon}
                     onChange={(e) => setTier(i, { addon: e.target.value })} placeholder="0.50" />
              <span className="text-xs text-gray-500">/ min</span>
              <button
                className="btn-danger text-xs px-2.5 py-1 ml-auto"
                onClick={() => set({ tiers: value.tiers.filter((_, j) => j !== i) })}
              >Remove</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 font-medium">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="text-[10px] text-gray-600 mt-1 block">{hint}</span>}
    </label>
  );
}
