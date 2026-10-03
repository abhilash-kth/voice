"use client";
import { useState } from "react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import { createProvider, updateProvider, type Provider } from "@/lib/api";

const KINDS = ["llm", "stt", "tts", "telephony"];

export default function ProviderFormModal({
  provider,
  defaultKind,
  onClose,
  onSaved,
}: {
  provider: Provider | null;      // null = create mode
  defaultKind: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const edit = provider !== null;
  const [kind, setKind] = useState(edit ? provider.kind : defaultKind);
  const [slug, setSlug] = useState(edit ? provider.slug : "");
  const [displayName, setDisplayName] = useState(edit ? provider.display_name : "");
  const [adapter, setAdapter] = useState(edit ? provider.adapter : "");
  const [baseUrl, setBaseUrl] = useState(edit ? provider.base_url : "");
  const [keyEnv, setKeyEnv] = useState(edit ? provider.key_env : "");
  const [tier, setTier] = useState(edit ? provider.tier : "paid");
  const [requiresKey, setRequiresKey] = useState(edit ? provider.requires_key : true);
  const [sortOrder, setSortOrder] = useState(edit ? String(provider.sort_order) : "0");
  const [notes, setNotes] = useState(edit ? provider.notes : "");
  const { busy, err, run } = useBusy();

  const submit = () => {
    run(async () => {
      if (edit) {
        await updateProvider(provider.id, {
          display_name: displayName.trim(), adapter: adapter.trim(),
          base_url: baseUrl.trim(), key_env: keyEnv.trim(),
          tier, requires_key: requiresKey, notes: notes.trim(),
        });
      } else {
        await createProvider({
          kind, slug: slug.trim().toLowerCase(),
          display_name: displayName.trim(), adapter: adapter.trim(),
          base_url: baseUrl.trim(), key_env: keyEnv.trim(),
          tier, requires_key: requiresKey, notes: notes.trim(),
          sort_order: Number(sortOrder) || 0,
        });
      }
      onSaved();
    }, edit ? "Provider updated ✓" : "Provider created ✓").then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit = edit ? true : slug.trim().length > 0;

  return (
    <Modal title={edit ? `Edit provider — ${provider.slug}` : "Add provider"} onClose={onClose}>
      <div className="space-y-3 text-sm">
        {err && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">⚠ {err}</div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Kind</span>
            <select className="input mt-1" value={kind} onChange={(e) => setKind(e.target.value)} disabled={edit}>
              {KINDS.map((k) => (
                <option key={k} value={k}>{k.toUpperCase()}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Slug (unique per kind, e.g. openai)</span>
            <input
              className="input mt-1" value={slug} disabled={edit}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, ""))}
              placeholder="openai"
            />
          </label>
        </div>

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Display name</span>
          <input className="input mt-1" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="OpenAI" />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Adapter (pipeline driver, e.g. openai)</span>
            <input className="input mt-1" value={adapter} onChange={(e) => setAdapter(e.target.value)} placeholder="openai / deepgram / sarvam …" />
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
          <span className="text-xs text-gray-400 font-medium">Base URL (blank = provider default)</span>
          <input className="input mt-1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
        </label>

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Key env var (fallback when no stored credential)</span>
          <input className="input mt-1" value={keyEnv} onChange={(e) => setKeyEnv(e.target.value)} placeholder="OPENAI_API_KEY" />
        </label>

        <label className="flex items-center gap-2 text-xs text-gray-300">
          <input
            type="checkbox" className="accent-blue-500 w-4 h-4"
            checked={requiresKey} onChange={(e) => setRequiresKey(e.target.checked)}
          />
          Requires API key (uncheck only for local/self-hosted endpoints)
        </label>

        {!edit && (
          <label className="block">
            <span className="text-xs text-gray-400 font-medium">Sort order (lower shows first)</span>
            <input className="input mt-1" type="number" value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} />
          </label>
        )}

        <label className="block">
          <span className="text-xs text-gray-400 font-medium">Notes (internal)</span>
          <input className="input mt-1" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="optional" />
        </label>

        <p className="text-[10px] text-gray-600">
          New providers are created DISABLED. Add models first, then enable. API keys are managed separately on the API Keys page.
        </p>

        <div className="flex justify-end gap-2 pt-1">
          <button className="btn-secondary text-xs" onClick={onClose}>Cancel</button>
          <button className="btn text-xs" disabled={busy || !canSubmit} onClick={submit}>
            {busy ? "Saving…" : edit ? "Save changes" : "Create provider"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
