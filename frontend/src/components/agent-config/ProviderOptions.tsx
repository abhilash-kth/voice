"use client";
import { ProviderDef } from "@/lib/api";

/**
 * The option selects for one picked provider (voice/model/…). Purely
 * presentational; the selected values live in the form's optionVals state.
 * (Formerly AgentConfigForm.renderOptions.)
 */
export default function ProviderOptions({
  provider, optKey, optionVals, onOption,
}: {
  provider: ProviderDef | undefined;
  optKey: string;                                   // optionKey(kind, pid, role)
  optionVals: Record<string, Record<string, string>>;
  onOption: (optKey: string, optName: string, value: string) => void;
}) {
  const p = provider as any;
  if (!p?.options) return null;
  // Non-array entries in options (e.g. cartesia's voice_labels map) are
  // metadata for labelling, not selects — Object.entries would otherwise try
  // to .map() a dict and crash the form.
  const voiceLabels: Record<string, string> =
    (p.options as Record<string, unknown>)?.voice_labels as Record<string, string> || {};
  return (
    <>
      {Object.entries(p.options as Record<string, unknown>).map(([optName, optVals]) => {
        if (!Array.isArray(optVals) || optVals.length === 0) return null;
        const current = optionVals[optKey]?.[optName] || optVals[0];
        const values = optVals.includes(current) ? optVals : [current, ...optVals];
        return (
          <label key={optName} className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400 font-medium">{optName}</span>
            <select
              className="input"
              value={current}
              onChange={(e) => onOption(optKey, optName, e.target.value)}
            >
              {values.map((o: string) => {
                let label = o;
                if (optName === "model" && p.cost?.per_1k_in != null) {
                  label = `${o} — ₹${p.cost.per_1k_in}/1K in · ₹${p.cost.per_1k_out}/1K out`;
                } else if (optName === "voice" && voiceLabels[o]) {
                  label = `${voiceLabels[o]} (${o.slice(0, 8)}…)`;
                }
                return (
                  <option key={o} value={o}>
                    {label}
                  </option>
                );
              })}
            </select>
          </label>
        );
      })}
    </>
  );
}

/** Shared toggle switch used on both form columns. */
export function Toggle({
  on, set, label, hint,
}: {
  on: boolean;
  set: (v: boolean) => void;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={() => set(!on)}
      className={`flex items-center justify-between w-full p-3 rounded-lg border text-left ${on ? "bg-blue-500/10 border-blue-500/30" : "bg-gray-800 border-gray-700"}`}
    >
      <span>
        <span className="block text-sm font-semibold">{label}</span>
        <span className="block text-[11px] text-gray-400">{hint}</span>
      </span>
      <span className={`w-10 h-6 rounded-full relative transition ${on ? "bg-blue-600" : "bg-gray-600"}`}>
        <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${on ? "left-[18px]" : "left-0.5"}`} />
      </span>
    </button>
  );
}
