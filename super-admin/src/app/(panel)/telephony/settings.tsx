"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Globe,
  KeyRound,
  Loader2,
  Network,
  Save,
  ShieldCheck,
} from "lucide-react";
import {
  testTelephonySettings,
  updateTelephonySettings,
  type TelephonySettings,
  type TelephonySettingsPatch,
} from "@/lib/api";
import { fmtDateTime, fmtINR } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface FormState {
  default_sip_trunk_id: string;
  voicelink_api_base_url: string;
  voicelink_api_token: string;
  clear_voicelink_api_token: boolean;
  voicelink_username: string;
  voicelink_password: string;
  clear_voicelink_password: boolean;
  voicelink_shared_trunk_username: string;
  voicelink_shared_trunk_password: string;
  clear_voicelink_shared_trunk_password: boolean;
  voicelink_sip_host: string;
  voicelink_sip_port: string;
  voicelink_tech_prefix: string;
  voicelink_transport_type: string;
  voicelink_audio_formats: string;
  voicelink_inbound_allowed_addresses: string;
  voicelink_wallet_bypass: boolean;
  voicelink_kyc_terms_url: string;
  voicelink_kyc_redirect_hosts: string;
  kyc_finalize_verified: boolean;
  livekit_sip_host: string;
  livekit_sip_port: string;
  frontend_url: string;
  public_api_url: string;
}

function toForm(settings: TelephonySettings): FormState {
  return {
    default_sip_trunk_id: settings.default_sip_trunk_id,
    voicelink_api_base_url: settings.voicelink_api_base_url,
    voicelink_api_token: "",
    clear_voicelink_api_token: false,
    voicelink_username: settings.voicelink_username,
    voicelink_password: "",
    clear_voicelink_password: false,
    voicelink_shared_trunk_username:
      settings.voicelink_shared_trunk_username,
    voicelink_shared_trunk_password: "",
    clear_voicelink_shared_trunk_password: false,
    voicelink_sip_host: settings.voicelink_sip_host,
    voicelink_sip_port: String(settings.voicelink_sip_port),
    voicelink_tech_prefix: settings.voicelink_tech_prefix,
    voicelink_transport_type: String(settings.voicelink_transport_type),
    voicelink_audio_formats: settings.voicelink_audio_formats.join(","),
    voicelink_inbound_allowed_addresses:
      settings.voicelink_inbound_allowed_addresses.join(","),
    voicelink_wallet_bypass: settings.voicelink_wallet_bypass,
    voicelink_kyc_terms_url: settings.voicelink_kyc_terms_url,
    voicelink_kyc_redirect_hosts:
      settings.voicelink_kyc_redirect_hosts.join(","),
    kyc_finalize_verified: settings.kyc_finalize_verified,
    livekit_sip_host: settings.livekit_sip_host,
    livekit_sip_port: String(settings.livekit_sip_port),
    frontend_url: settings.frontend_url,
    public_api_url: settings.public_api_url,
  };
}

const splitCsv = (value: string) =>
  value.split(/[\n,]/).map((v) => v.trim()).filter(Boolean);

function Section({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <Card className="space-y-4 p-5 shadow-xs">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Icon className="h-4 w-4 text-primary" /> {title}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </Card>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
      {hint && <p className="text-[11px] leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}

function SecretState({
  configured,
  masked,
}: {
  configured: boolean;
  masked: string;
}) {
  if (!configured && masked) {
    return (
      <p className="flex items-center gap-1.5 text-[11px] text-amber-700 dark:text-amber-300">
        <AlertTriangle className="h-3.5 w-3.5" />
        A saved value ({masked}) could not be decrypted—re-enter it.
      </p>
    );
  }
  return configured ? (
    <p className="flex items-center gap-1.5 text-[11px] text-emerald-700 dark:text-emerald-300">
      <CheckCircle2 className="h-3.5 w-3.5" />
      Saved {masked ? `· ${masked}` : "· configured"}
    </p>
  ) : (
    <p className="text-[11px] text-muted-foreground">Not configured</p>
  );
}

export function TelephonySettingsForm({
  initial,
  onSaved,
}: {
  initial: TelephonySettings;
  onSaved: (settings: TelephonySettings) => void;
}) {
  const [form, setForm] = useState<FormState>(() => toForm(initial));
  const [busy, setBusy] = useState<"" | "save" | "test">("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [testResult, setTestResult] = useState("");

  useEffect(() => {
    setForm(toForm(initial));
  }, [initial]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSuccess("");
    setTestResult("");
  };

  const textField = (
    label: string,
    key: keyof FormState,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
    hint?: string,
  ) => (
    <Field label={label} hint={hint}>
      <Input
        value={String(form[key] ?? "")}
        disabled={busy !== ""}
        onChange={(e) => set(key, e.target.value as FormState[typeof key])}
        {...props}
      />
    </Field>
  );

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setTestResult("");

    const voicelinkPort = Number(form.voicelink_sip_port);
    const livekitPort = Number(form.livekit_sip_port);
    const transport = Number(form.voicelink_transport_type);
    if (![voicelinkPort, livekitPort].every(
      (p) => Number.isInteger(p) && p >= 1 && p <= 65535,
    )) {
      setError("SIP ports must be whole numbers between 1 and 65535.");
      return;
    }
    if (!Number.isInteger(transport) || transport < 1 || transport > 10) {
      setError("VoiceLink transport type must be a provider code from 1 to 10.");
      return;
    }

    if (
      form.kyc_finalize_verified &&
      !initial.kyc_finalize_verified &&
      !window.confirm(
        "Enable client KYC final-submit? Only do this after VoiceLink confirms in writing that POST /reseller/kyc/final-submit acts only on the supplied client_id. Enabling it without that confirmation can finalize the wrong account.",
      )
    ) {
      return;
    }
    if (
      form.voicelink_wallet_bypass &&
      !initial.voicelink_wallet_bypass &&
      !window.confirm(
        "Enable VoiceLink wallet bypass? New customer clients may then draw directly from the reseller wallet. Keep this off unless VoiceLink's wallet semantics and customer isolation are confirmed.",
      )
    ) {
      return;
    }

    const patch: TelephonySettingsPatch = {
      default_sip_trunk_id: form.default_sip_trunk_id.trim(),
      voicelink_api_base_url: form.voicelink_api_base_url.trim(),
      clear_voicelink_api_token: form.clear_voicelink_api_token,
      voicelink_username: form.voicelink_username.trim(),
      clear_voicelink_password: form.clear_voicelink_password,
      voicelink_shared_trunk_username:
        form.voicelink_shared_trunk_username.trim(),
      clear_voicelink_shared_trunk_password:
        form.clear_voicelink_shared_trunk_password,
      voicelink_sip_host: form.voicelink_sip_host.trim(),
      voicelink_sip_port: voicelinkPort,
      voicelink_tech_prefix: form.voicelink_tech_prefix.trim(),
      voicelink_transport_type: transport,
      voicelink_audio_formats: splitCsv(form.voicelink_audio_formats),
      voicelink_inbound_allowed_addresses: splitCsv(
        form.voicelink_inbound_allowed_addresses,
      ),
      voicelink_wallet_bypass: form.voicelink_wallet_bypass,
      voicelink_kyc_terms_url: form.voicelink_kyc_terms_url.trim(),
      voicelink_kyc_redirect_hosts: splitCsv(
        form.voicelink_kyc_redirect_hosts,
      ),
      kyc_finalize_verified: form.kyc_finalize_verified,
      livekit_sip_host: form.livekit_sip_host.trim(),
      livekit_sip_port: livekitPort,
      frontend_url: form.frontend_url.trim(),
      public_api_url: form.public_api_url.trim(),
    };
    if (!form.clear_voicelink_api_token && form.voicelink_api_token.trim()) {
      patch.voicelink_api_token = form.voicelink_api_token.trim();
    }
    if (!form.clear_voicelink_password && form.voicelink_password) {
      patch.voicelink_password = form.voicelink_password;
    }
    if (
      !form.clear_voicelink_shared_trunk_password &&
      form.voicelink_shared_trunk_password
    ) {
      patch.voicelink_shared_trunk_password =
        form.voicelink_shared_trunk_password;
    }

    setBusy("save");
    try {
      const out = await updateTelephonySettings(patch);
      setForm(toForm(out.settings));
      onSaved(out.settings);
      setSuccess(
        "Telephony settings saved to the database. New VoiceLink/provisioning requests use them immediately; no backend restart is needed for these values.",
      );
    } catch (err) {
      setError((err as Error).message || "Telephony settings could not be saved.");
    } finally {
      setBusy("");
    }
  };

  const test = async () => {
    setBusy("test");
    setError("");
    setTestResult("");
    try {
      const out = await testTelephonySettings();
      const p = out.profile || {};
      const parts = [
        "VoiceLink connection OK",
        p.id ? `provider account ${p.id}` : null,
        `active: ${p.active ? "yes" : "no"}`,
        `verified: ${p.verified ? "yes" : "no"}`,
        p.plan_name ? `plan: ${p.plan_name}` : null,
        p.wallet_balance !== undefined
          ? `wallet: ${fmtINR(Number(p.wallet_balance || 0))}`
          : null,
        p.channels_available !== undefined
          ? `available channels: ${p.channels_available}`
          : null,
      ].filter(Boolean);
      setTestResult(parts.join(" · "));
    } catch (err) {
      setError((err as Error).message || "VoiceLink connection test failed.");
    } finally {
      setBusy("");
    }
  };

  return (
    <form onSubmit={save} className="space-y-4">
      <Card className="p-4 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={initial.configured ? "default" : "destructive"}>
            {initial.configured ? "VoiceLink configured" : "VoiceLink not configured"}
          </Badge>
          <Badge variant="secondary">
            Source: {initial.source === "super_admin" ? "Super Admin database" : "Env fallback"}
          </Badge>
          {initial.updated_at && (
            <span className="text-xs text-muted-foreground">
              Updated {fmtDateTime(initial.updated_at)}
            </span>
          )}
        </div>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          These database settings replace the telephony section of{" "}
          <code className="font-mono text-foreground">backend/.env</code>. Existing
          env values are copied here once; afterwards, edit them only in this
          panel. One-time server bootstrap still stays in env: DATABASE_URL,
          JWT_SECRET, ADMIN_CONFIG_ENC_KEY, and the LiveKit server
          URL/API key/API secret shared by the voice worker.
        </p>
        {initial.source !== "super_admin" && (
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-xs leading-relaxed text-destructive">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            The database settings table is unavailable, so env fallback is being
            shown. Run Prisma db push + generate, restart the backend, then
            reload this tab before saving.
          </p>
        )}
        {!initial.encryption_key_configured && (
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            ADMIN_CONFIG_ENC_KEY is not set, so saved telephony secrets use
            the development JWT-derived fallback. Set a real encryption key in
            the server environment once before production use.
          </p>
        )}
      </Card>

      {error && (
        <p className="flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </p>
      )}
      {success && (
        <p className="flex items-start gap-2 rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-800 dark:text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> {success}
        </p>
      )}
      {testResult && (
        <p className="flex items-start gap-2 rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-800 dark:text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> {testResult}
        </p>
      )}

      <Section
        title="VoiceLink reseller API"
        description="Operator-only credentials. Secret boxes are write-only: leave blank to keep the saved value, type a new value to rotate it, or tick clear to remove it."
        icon={KeyRound}
      >
        <div className="grid gap-4 md:grid-cols-2">
          {textField("API base URL", "voicelink_api_base_url", {
            required: true,
            placeholder: "https://app.voicelink.co.in/api/v1",
          })}
          <Field label="API token (preferred)">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.voicelink_api_token}
              disabled={busy !== "" || form.clear_voicelink_api_token}
              onChange={(e) => set("voicelink_api_token", e.target.value)}
              placeholder={
                initial.voicelink_api_token_configured
                  ? "Leave blank to keep saved token"
                  : "Paste token without “Bearer ”"
              }
            />
            <SecretState
              configured={initial.voicelink_api_token_configured}
              masked={initial.voicelink_api_token_masked}
            />
            <label className="flex items-center gap-2 pt-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={form.clear_voicelink_api_token}
                disabled={busy !== ""}
                onChange={(e) => set("clear_voicelink_api_token", e.target.checked)}
                className="h-3.5 w-3.5 accent-primary"
              />
              Clear saved token
            </label>
          </Field>
          {textField("Fallback login username", "voicelink_username", {
            autoComplete: "off",
          })}
          <Field label="Fallback login password">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.voicelink_password}
              disabled={busy !== "" || form.clear_voicelink_password}
              onChange={(e) => set("voicelink_password", e.target.value)}
              placeholder={
                initial.voicelink_password_configured
                  ? "Leave blank to keep saved password"
                  : "Used only when no API token is saved"
              }
            />
            <SecretState
              configured={initial.voicelink_password_configured}
              masked={initial.voicelink_password_masked}
            />
            <label className="flex items-center gap-2 pt-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={form.clear_voicelink_password}
                disabled={busy !== ""}
                onChange={(e) => set("clear_voicelink_password", e.target.checked)}
                className="h-3.5 w-3.5 accent-primary"
              />
              Clear saved password
            </label>
          </Field>
        </div>
      </Section>

      <Section
        title="SIP routing"
        description="Shared Oracle LiveKit SIP destination plus VoiceLink gateway values. Purchased numbers still receive their own logical trunks; this does not create or restart SIP/Redis services."
        icon={Network}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {textField("VoiceLink SIP host", "voicelink_sip_host", {
            required: true,
            placeholder: "sip.voicelink.co.in",
          })}
          {textField("VoiceLink SIP port", "voicelink_sip_port", {
            required: true,
            type: "number",
            min: 1,
            max: 65535,
          })}
          {textField("Carrier tech prefix", "voicelink_tech_prefix", {
            inputMode: "numeric",
            placeholder: "45454",
          }, "Dial format is prefix + 91 + 10-digit number.")}
          {textField("Public LiveKit SIP host", "livekit_sip_host", {
            placeholder: "c{client_id}.kvoice.duckdns.org",
          }, "Hostname/IP only—no scheme or port. Use {client_id} for a per-client wildcard DNS alias because VoiceLink requires a unique host and will not route a DID through another client's trunk.")}
          {textField("Public LiveKit SIP port", "livekit_sip_port", {
            required: true,
            type: "number",
            min: 1,
            max: 65535,
          })}
          {textField(
            "VoiceLink inbound source IPs/CIDRs",
            "voicelink_inbound_allowed_addresses",
            { placeholder: "160.30.71.113/32" },
            "Comma-separated. VoiceLink does not answer LiveKit's inbound 407 digest challenge, so purchased-number inbound trunks use no SIP password and should be restricted to VoiceLink signalling sources. Ask VoiceLink for the full range; after changing this, click Sync inbound on each active number.",
          )}
          {textField("Default fallback LiveKit trunk ID", "default_sip_trunk_id", {
            placeholder: "ST_… (optional)",
          }, "Only for legacy agents without an assigned purchased number.")}
          <Field
            label="VoiceLink transport code"
            hint="1=UDP / 2=TCP / 3=TLS is inferred from the SDK; keep 1 unless VoiceLink confirms otherwise."
          >
            <select
              value={form.voicelink_transport_type}
              disabled={busy !== ""}
              onChange={(e) => set("voicelink_transport_type", e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="1">1 — UDP</option>
              <option value="2">2 — TCP</option>
              <option value="3">3 — TLS</option>
              {!["1", "2", "3"].includes(form.voicelink_transport_type) && (
                <option value={form.voicelink_transport_type}>
                  {form.voicelink_transport_type} — saved custom code
                </option>
              )}
            </select>
          </Field>
          {textField("Audio formats (comma-separated)", "voicelink_audio_formats", {
            required: true,
            placeholder: "alaw,ulaw",
          })}
          {textField(
            "Existing shared VoiceLink trunk username",
            "voicelink_shared_trunk_username",
            { autoComplete: "off" },
            "Legacy fallback only for an existing trunk owned by the same VoiceLink client as the DID. This is not the API login username; cross-client trunks cannot be reused.",
          )}
          <Field
            label="Existing shared VoiceLink trunk SIP password"
            hint="Required only when VoiceLink's trunk list omits the existing trunk password. Copy it exactly from that trunk; changing it here does not change VoiceLink."
          >
            <Input
              type="password"
              autoComplete="new-password"
              value={form.voicelink_shared_trunk_password}
              disabled={
                busy !== "" || form.clear_voicelink_shared_trunk_password
              }
              onChange={(e) =>
                set("voicelink_shared_trunk_password", e.target.value)
              }
              placeholder={
                initial.voicelink_shared_trunk_password_configured
                  ? "Leave blank to keep saved trunk password"
                  : "Existing trunk registration/SIP password"
              }
            />
            <SecretState
              configured={initial.voicelink_shared_trunk_password_configured}
              masked={initial.voicelink_shared_trunk_password_masked}
            />
            <label className="flex items-center gap-2 pt-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={form.clear_voicelink_shared_trunk_password}
                disabled={busy !== ""}
                onChange={(e) =>
                  set(
                    "clear_voicelink_shared_trunk_password",
                    e.target.checked,
                  )
                }
                className="h-3.5 w-3.5 accent-primary"
              />
              Clear saved shared trunk password
            </label>
          </Field>
        </div>
      </Section>

      <Section
        title="KYC and public URLs"
        description="Browser return URLs and provider KYC safety switches. Customers still complete KYC on your website; these values never expose VoiceLink credentials."
        icon={ShieldCheck}
      >
        <div className="grid gap-4 md:grid-cols-2">
          {textField("Customer app URL", "frontend_url", {
            required: true,
            placeholder: "https://agents.example.com",
          }, "DigiLocker returns the browser to this origin + /phone-numbers.")}
          {textField("Public API URL (optional)", "public_api_url", {
            placeholder: "https://api.example.com",
          }, "Leave blank to use the API request origin for the KYC return endpoint.")}
          {textField("VoiceLink-hosted KYC terms URL", "voicelink_kyc_terms_url", {
            placeholder: "https://app.voicelink.co.in/…",
          })}
          {textField("Extra DigiLocker redirect hosts", "voicelink_kyc_redirect_hosts", {
            placeholder: "Comma-separated hostnames",
          }, "Official DigiLocker hosts, including api.digitallocker.gov.in, are always allowed.")}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-start gap-3 rounded-lg border border-border/60 p-3 text-sm">
            <input
              type="checkbox"
              checked={form.voicelink_wallet_bypass}
              disabled={busy !== ""}
              onChange={(e) => set("voicelink_wallet_bypass", e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-primary"
            />
            <span>
              <strong className="font-medium">VoiceLink wallet bypass</strong>
              <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                Applies when new hidden VoiceLink clients are created. Keep off
                unless provider wallet isolation is confirmed.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
            <input
              type="checkbox"
              checked={form.kyc_finalize_verified}
              disabled={busy !== ""}
              onChange={(e) => set("kyc_finalize_verified", e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-primary"
            />
            <span>
              <strong className="font-medium">VoiceLink confirmed client KYC final-submit</strong>
              <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                Enable only after written confirmation that final-submit
                honours client_id. Until then, final submission stays gated.
              </span>
            </span>
          </label>
        </div>
      </Section>

      <Card className="flex flex-col gap-3 p-4 shadow-xs sm:flex-row sm:items-center">
        <Button type="submit" disabled={busy !== ""}>
          {busy === "save" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save settings
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy !== "" || !initial.configured}
          onClick={() => void test()}
        >
          {busy === "test" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Globe className="mr-2 h-4 w-4" />
          )}
          Test saved connection
        </Button>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Save first, then test. The test reads only the reseller profile and
          returns no token, password or SIP secret.
        </p>
      </Card>
    </form>
  );
}
