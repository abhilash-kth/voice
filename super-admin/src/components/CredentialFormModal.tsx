"use client";

import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Info,
  Loader2,
  RefreshCw,
  Plus,
  Lock,
} from "lucide-react";
import Modal from "@/components/Modal";
import { useBusy } from "@/components/PageHeader";
import {
  createCredential,
  rotateCredential,
  type Credential,
  type Provider,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function CredentialFormModal({
  mode, // "create" | "rotate"
  credential, // rotate mode: the existing credential
  providers, // create mode: pickable providers
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
  const [providerId, setProviderId] = useState(
    create ? "" : credential!.provider_id,
  );
  const [value, setValue] = useState("");
  const [label, setLabel] = useState(create ? "" : credential!.label);
  const { busy, err, run } = useBusy();

  const submit = () => {
    run(
      async () => {
        if (create) {
          await createCredential({
            provider_id: providerId,
            value: value.trim(),
            label: label.trim(),
          });
        } else {
          await rotateCredential(credential!.id, value.trim(), label.trim());
        }
        onSaved();
      },
      create ? "Key stored (encrypted) ✓" : "Key rotated ✓",
    ).then((ok) => {
      if (ok !== undefined) onClose();
    });
  };

  const canSubmit =
    value.trim().length > 0 && (create ? providerId.length > 0 : true);

  return (
    <Modal
      title={
        create
          ? "Add provider API key"
          : `Rotate key — ${credential?.provider_slug}`
      }
      onClose={onClose}
    >
      <div className="space-y-4 text-sm">
        {err && (
          <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/5 px-3.5 py-3 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <span className="leading-relaxed">{err}</span>
          </div>
        )}

        {!create && (
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3.5 py-3 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <span className="leading-relaxed">
              Rotating replaces the old key immediately. Calls in progress keep
              their old key until they end; new calls use the new key.
            </span>
          </div>
        )}

        {create && (
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
                  [{p.kind.toUpperCase()}] {p.slug}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            {create ? "API key" : "New API key"}
          </Label>
          <Input
            className="h-9 font-mono text-sm"
            type="password"
            autoComplete="off"
            placeholder="sk-…"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-muted-foreground">
            Label{" "}
            <span className="font-normal text-muted-foreground/70">
              (e.g. production, backup — shown in lists)
            </span>
          </Label>
          <Input
            className="h-9"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="production"
          />
        </div>

        <div className="flex items-start gap-2.5 rounded-lg border border-border/50 bg-muted/20 p-3">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Keys are encrypted (Fernet) BEFORE touching the database and are
            never returned by any API — you will only ever see the masked form
            (e.g. sk-…wxyz). The plaintext leaves your browser exactly once.
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
            ) : create ? (
              <>
                <Plus className="mr-2 h-3.5 w-3.5" />
                Store key
              </>
            ) : (
              <>
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                Rotate key
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
