// Small on/off toggle used across the agent form sections.
// Extracted from AgentConfigForm.tsx (verbatim) — no behavior change.

export function Toggle({
  on,
  set,
  label,
  hint,
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
