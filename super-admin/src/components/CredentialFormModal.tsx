"use client";
import { useState } from "react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import { createCredential, rotateCredential, type Credential, type Provider } from "@/lib/api";

export default function CredentialFormModal({
  mode,                       // "create" | "rotate"
  credential,                 // rotate mode: the existing credential
  providers,                  // create mode: pickable providers
  takenSlugs = [],            // slugs that already have an ACTIVE key (dupes blocked)
  onClose,
  onSaved,
}: {
  mode: "create" | "rotate";
  credential?: Credential;
  providers: Provider[];
  takenSlugs?: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const create = mode === "create";
  const [providerId, setProviderId] = useState(create ? "" : credential!.provider_id);
  const [value, setValue] = useState("");
  const [label, setLabel] = useState(create ? "" : credential!.label);
  const { busy, err, run } = useBusy();

  // One key per provider: collapse all of a slug's kind-rows (LLM/STT/TTS) into
  // a single choice, and hide providers that already have an active key —
  // duplicates are rejected server-side as well.
  const bySlug = new Map<string, { id: string; slug: string; kinds: string[] }>();
  for (const p of providers) {
    const e = bySlug.get(p.slug) || { id: p.id, slug: p.slug, kinds: [] };
    if (!e.kinds.includes(p.kind)) e.kinds.push(p.kind);
    bySlug.set(p.slug, e);
  }
  const choices = Array.from(bySlug.values());
  const available = choices.filter((c) => !takenSlugs.includes(c.slug));
  const taken = choices.filter((c) => takenSlugs.includes(c.slug));

  const submit = () => {
    run(async () => {
      if (create) {
        await createCredential({ provider_id: providerId, value: value.trim(), label: label.trim() });
      } else {
        await rotateCredential(credential!.id, value.trim(), label.trim());
      }
      onSaved();
    }, create ? "Key stored (encrypted) ✓" : "Key rotated ✓").then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit = value.trim().length > 0 && (create ? providerId.length > 0 : true);

  return (
    <Modal
      title={create ? "Add provider API key" : `Rotate key — ${credential?.provider_slug}`}
      onClose={onClose}
    >
      <div className="space-y-3 text-sm">
        {err && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">⚠ {err}</div>
        )}

        {!create && (
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs">
            ⚠ Rotating replaces the old key immediately. Calls in progress keep their old key until they end; new calls use the new key.
          </div>
        )}

        {create && (
          <>
            <label className="block">
              <span className="text-xs text-gray-400 font-medium">Provider (one key covers all its services)</span>
              <select className="input mt-1" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                <option value="">Select…</option>
                {available.map((c) => (
                  <option key={c.slug} value={c.id}>
                    {c.slug} — {c.kinds.map((k) => k.toUpperCase()).join(" + ")}
                  </option>
                ))}
              </select>
            </label>
            {taken.length > 0 && (
              <p className="text-[10px] text-amber-400/90">
                Already has an active key (Rotate instead): {taken.map((t) => t.slug).join(", ")}
              </p>
            )}
          </>
        )}

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">
            {create ? "API key" : "New API key"}
          </span>
          <input
            className="input mt-1 font-mono" type="password" autoComplete="off"
            placeholder="sk-…" value={value} onChange={(e) => setValue(e.target.value)}
          />
        </label>

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Label (e.g. production, backup — shown in lists)</span>
          <input className="input mt-1" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="production" />
        </label>

        <p className="text-[10px] text-gray-600">
          Keys are encrypted (Fernet) BEFORE touching the database. A shared key serves every service of the
          provider — e.g. one Sarvam key covers its STT and LLM, one OpenAI key covers its LLM and TTS.
          Duplicate keys for the same provider are rejected; use Rotate to replace one.
        </p>

        <div className="flex justify-end gap-2 pt-1">
          <button className="btn-secondary text-xs" onClick={onClose}>Cancel</button>
          <button className="btn text-xs" disabled={busy || !canSubmit} onClick={submit}>
            {busy ? "Saving…" : create ? "Store key" : "Rotate key"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
