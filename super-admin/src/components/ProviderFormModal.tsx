"use client";

import { useState } from "react";
import { AlertCircle, Info, Loader2, Save, Plus } from "lucide-react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import { createProvider, updateProvider, type Provider } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const KINDS = ["llm", "stt", "tts", "telephony"];

export default function ProviderFormModal({
  provider,
  defaultKind,
  onClose,
  onSaved,
}: {
  provider: Provider | null; // null = create mode
  defaultKind: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const edit = provider !== null;
  const [kind, setKind] = useState(edit ? provider.kind : defaultKind);
  const [slug, setSlug] = useState(edit ? provider.slug : "");
  const [displayName, setDisplayName] = useState(
    edit ? provider.display_name : "",
  );
  const [adapter, setAdapter] = useState(edit ? provider.adapter : "");
  const [baseUrl, setBaseUrl] = useState(edit ? provider.base_url : "");
  const [keyEnv, setKeyEnv] = useState(edit ? provider.key_env : "");
  const [tier, setTier] = useState(edit ? provider.tier : "paid");
  const [requiresKey, setRequiresKey] = useState(
    edit ? provider.requires_key : true,
  );
  const [sortOrder, setSortOrder] = useState(
    edit ? String(provider.sort_order) : "0",
  );
  const [notes, setNotes] = useState(edit ? provider.notes : "");
  const { busy, err, run } = useBusy();

  const submit = () => {
    run(
      async () => {
        if (edit) {
          await updateProvider(provider.id, {
            display_name: displayName.trim(),
            adapter: adapter.trim(),
            base_url: baseUrl.trim(),
            key_env: keyEnv.trim(),
            tier,
            requires_key: requiresKey,
            notes: notes.trim(),
          });
        } else {
          await createProvider({
            kind,
            slug: slug.trim().toLowerCase(),
            display_name: displayName.trim(),
            adapter: adapter.trim(),
            base_url: baseUrl.trim(),
            key_env: keyEnv.trim(),
            tier,
            requires_key: requiresKey,
            notes: notes.trim(),
            sort_order: Number(sortOrder) || 0,
          });
        }
        onSaved();
      },
      edit ? "Provider updated ✓" : "Provider created ✓",
    ).then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit = edit ? true : slug.trim().length > 0;

  return (
    <Modal
      title={edit ? `Edit provider — ${provider.slug}` : "Add provider"}
      onClose={onClose}
    >
      <div className="space-y-4 text-sm">
        {err && (
          <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/5 px-3.5 py-3 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <span className="leading-relaxed">{err}</span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Kind
            </Label>
            <select
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              disabled={edit}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Slug{" "}
              <span className="font-normal text-muted-foreground/70">
                (unique per kind)
              </span>
            </Label>
            <Input
              className="h-9 font-mono text-sm"
              value={slug}
              disabled={edit}
              onChange={(e) =>
                setSlug(
                  e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, ""),
                )
              }
              placeholder="openai"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Display name
          </Label>
          <Input
            className="h-9"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="OpenAI"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Adapter{" "}
              <span className="font-normal text-muted-foreground/70">
                (pipeline driver)
              </span>
            </Label>
            <Input
              className="h-9 font-mono text-sm"
              value={adapter}
              onChange={(e) => setAdapter(e.target.value)}
              placeholder="openai / deepgram / sarvam …"
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
            Base URL{" "}
            <span className="font-normal text-muted-foreground/70">
              (blank = provider default)
            </span>
          </Label>
          <Input
            className="h-9 font-mono text-sm"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Key env var{" "}
            <span className="font-normal text-muted-foreground/70">
              (fallback when no stored credential)
            </span>
          </Label>
          <Input
            className="h-9 font-mono text-sm"
            value={keyEnv}
            onChange={(e) => setKeyEnv(e.target.value)}
            placeholder="OPENAI_API_KEY"
          />
        </div>

        <div className="flex items-center gap-2 pt-1">
          <input
            type="checkbox"
            id="requires-key"
            className="h-4 w-4 rounded border-input text-primary accent-primary focus:ring-ring cursor-pointer"
            checked={requiresKey}
            onChange={(e) => setRequiresKey(e.target.checked)}
          />
          <Label
            htmlFor="requires-key"
            className="text-xs font-normal text-foreground cursor-pointer"
          >
            Requires API key{" "}
            <span className="text-muted-foreground">
              (uncheck only for local/self-hosted endpoints)
            </span>
          </Label>
        </div>

        {!edit && (
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">
              Sort order{" "}
              <span className="font-normal text-muted-foreground/70">
                (lower shows first)
              </span>
            </Label>
            <Input
              className="h-9 tabular-nums"
              type="number"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
            />
          </div>
        )}

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Notes{" "}
            <span className="font-normal text-muted-foreground/70">
              (internal)
            </span>
          </Label>
          <Input
            className="h-9"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="optional"
          />
        </div>

        <div className="flex items-start gap-2.5 rounded-lg border border-border/50 bg-muted/20 p-3">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            New providers are created DISABLED. Add models first, then enable.
            API keys are managed separately on the API Keys page.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-2">
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
                Create provider
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
