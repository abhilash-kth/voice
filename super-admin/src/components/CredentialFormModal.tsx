"use client";
import { useState } from "react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import { createCredential, rotateCredential, type Credential, type Provider } from "@/lib/api";

export default function CredentialFormModal({
  mode,                       // "create" | "rotate"
  credential,                 // rotate mode: the existing credential
  providers,                  // create mode: pickable providers
  onClose,
  onSaved,
}: {
  mode: "create" | "rotate";
  credential?: Credential;
  providers: Provider[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const create = mode === "create";
  const [providerId, setProviderId] = useState(create ? "" : credential!.provider_id);
  const [value, setValue] = useState("");
  const [label, setLabel] = useState(create ? "" : credential!.label);
  const { busy, err, run } = useBusy();

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
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Provider</span>
            <select className="input mt-1" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
              <option value="">Select…</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  [{p.kind.toUpperCase()}] {p.slug}
                </option>
              ))}
            </select>
          </label>
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
          Keys are encrypted (Fernet) BEFORE touching the database and are never returned by any API —
          you will only ever see the masked form (e.g. sk-…wxyz). The plaintext leaves your browser exactly once.
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
