"use client";

import { useState } from "react";
import { CheckCircle2, ExternalLink, Loader2, ShieldCheck, Upload } from "lucide-react";
import { toast } from "sonner";
import {
  kycAction,
  uploadKycDocument,
  type KycState,
} from "@/lib/telephony";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const inputCls = "h-9 bg-background";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

export default function KycPanel({
  kyc,
  onChanged,
}: {
  kyc: KycState;
  onChanged: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [editDetails, setEditDetails] = useState(false);
  const [accountType, setAccountType] = useState(kyc.account_type || "individual");
  const [terms, setTerms] = useState(false);
  const [details, setDetails] = useState({
    full_name: "",
    business_name: "",
    phone: "",
    billing_address: "",
    state: "",
    city: "",
    pincode: "",
  });
  const [pan, setPan] = useState("");
  const [holder, setHolder] = useState("");
  const [gst, setGst] = useState("");
  const [otp, setOtp] = useState("");

  const act = async (action: string, extra: Record<string, unknown> = {}) => {
    if (busy) return;
    setBusy(true);
    try {
      const out = await kycAction({ action, ...extra });
      if (action === "aadhaar" && out.redirect_url) {
        window.location.assign(out.redirect_url);
        return;
      }
      if (out.warning) toast.warning(out.warning);
      else toast.success(out.message || "Verification progress updated.");
      setEditDetails(false);
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Verification step failed.");
    } finally {
      setPan("");
      setGst("");
      setOtp("");
      setBusy(false);
    }
  };

  const upload = async (type: string, file: File, el: HTMLInputElement) => {
    if (busy) return;
    if (file.size > 3 * 1024 * 1024) {
      toast.error("Choose a document up to 3 MB.");
      el.value = "";
      return;
    }
    setBusy(true);
    try {
      await uploadKycDocument(type, file);
      toast.success("Document sent securely for verification.");
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message || "Document upload failed.");
    } finally {
      el.value = "";
      setBusy(false);
    }
  };

  const uploadField = (type: string, label: string) => (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <Input
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          disabled={busy}
          className={inputCls}
          onChange={(e) => {
            const f = e.currentTarget.files?.[0];
            if (f) void upload(type, f, e.currentTarget);
          }}
        />
        <Upload className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
      <p className="text-[11px] text-muted-foreground">
        PDF/JPG/PNG up to 3 MB. Forwarded to the verification provider; not
        stored in your workspace.
      </p>
    </Field>
  );

  if (kyc.status === "verified") {
    return (
      <section className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-5">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div>
            <h3 className="text-sm font-semibold">Identity verified</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              KYC is complete. You can buy a number and it will activate
              automatically.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const steps: [string, boolean][] = [
    ["Details", kyc.step !== "register"],
    ["PAN", !!(kyc.documents.pan?.verified && kyc.documents.pan?.uploaded)],
    [
      "Aadhaar",
      !!(kyc.documents.aadhaar?.verified && kyc.documents.aadhaar?.uploaded),
    ],
    ["Final", kyc.provider_complete],
  ];

  return (
    <section className="space-y-5 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <ShieldCheck className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">Verify your identity (KYC)</h3>
            <Badge variant="outline" className="capitalize">
              {kyc.status.replace(/_/g, " ")}
            </Badge>
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            Complete verification here — no separate provider account or
            password is needed. Identity details and documents are forwarded
            securely for verification and are not saved in your workspace.
          </p>
        </div>
      </div>

      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {steps.map(([label, done]) => (
          <li
            key={label}
            className={cn(
              "rounded-lg border px-3 py-2 text-xs font-medium",
              done
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-border text-muted-foreground",
            )}
          >
            {done ? "✓ " : ""}
            {label}
          </li>
        ))}
      </ol>

      {kyc.agreement_needs_acceptance && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm leading-relaxed text-amber-800 dark:text-amber-300">
          The verification provider is asking for an additional agreement
          acceptance. Your completed steps are saved; support may need to
          confirm how this provider agreement is presented before final
          submission can continue.
        </p>
      )}

      {(kyc.step === "register" || editDetails) ? (
        <form
          className="space-y-4 rounded-lg border border-border/70 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void act("register", {
              ...details,
              account_type: accountType,
              accept_terms: terms,
            });
          }}
        >
          <h4 className="text-sm font-semibold">Your verification details</h4>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Account type">
              <select
                value={accountType}
                disabled={busy}
                onChange={(e) => setAccountType(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="individual">Individual</option>
                <option value="business">Business</option>
              </select>
            </Field>
            <Field label="Full legal name">
              <Input
                required
                value={details.full_name}
                disabled={busy}
                onChange={(e) =>
                  setDetails({ ...details, full_name: e.target.value })
                }
                className={inputCls}
              />
            </Field>
            {accountType === "business" && (
              <Field label="Business name">
                <Input
                  required
                  value={details.business_name}
                  disabled={busy}
                  onChange={(e) =>
                    setDetails({ ...details, business_name: e.target.value })
                  }
                  className={inputCls}
                />
              </Field>
            )}
            <Field label="Contact number (+91)">
              <Input
                required
                value={details.phone}
                disabled={busy}
                onChange={(e) => setDetails({ ...details, phone: e.target.value })}
                className={inputCls}
                placeholder="+91XXXXXXXXXX"
              />
            </Field>
            <Field label="Billing address">
              <Input
                required
                value={details.billing_address}
                disabled={busy}
                onChange={(e) =>
                  setDetails({ ...details, billing_address: e.target.value })
                }
                className={inputCls}
              />
            </Field>
            <Field label="State">
              <Input
                required
                value={details.state}
                disabled={busy}
                onChange={(e) => setDetails({ ...details, state: e.target.value })}
                className={inputCls}
              />
            </Field>
            <Field label="City">
              <Input
                required
                value={details.city}
                disabled={busy}
                onChange={(e) => setDetails({ ...details, city: e.target.value })}
                className={inputCls}
              />
            </Field>
            <Field label="Postal code">
              <Input
                required
                maxLength={6}
                value={details.pincode}
                disabled={busy}
                onChange={(e) =>
                  setDetails({ ...details, pincode: e.target.value })
                }
                className={inputCls}
              />
            </Field>
          </div>
          {kyc.terms_url ? (
            <a
              href={kyc.terms_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary underline"
            >
              Read verification terms <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
          <label className="flex items-start gap-2 text-sm leading-relaxed">
            <input
              type="checkbox"
              className="mt-1"
              checked={terms}
              disabled={busy}
              onChange={(e) => setTerms(e.target.checked)}
            />
            I accept the telecom verification terms and compliance requirements
            for activating phone services.
          </label>
          <Button type="submit" disabled={busy || !terms}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Save verification details
          </Button>
        </form>
      ) : (
        <Button type="button" variant="ghost" disabled={busy} onClick={() => setEditDetails(true)}>
          Review or update legal details
        </Button>
      )}

      {!editDetails && kyc.step !== "register" && (
        <div className="space-y-4">
          <form
            className="space-y-4 rounded-lg border border-border/70 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              void act("pan", { pan_number: pan, pan_holder_name: holder });
            }}
          >
            <h4 className="text-sm font-semibold">PAN verification</h4>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="PAN number">
                <Input
                  value={pan}
                  disabled={busy || kyc.documents.pan?.verified}
                  onChange={(e) => setPan(e.target.value.toUpperCase())}
                  className={inputCls}
                  placeholder={kyc.documents.pan?.verified ? "Verified" : "ABCDE1234F"}
                />
              </Field>
              <Field label="Name on PAN">
                <Input
                  value={holder}
                  disabled={busy || kyc.documents.pan?.verified}
                  onChange={(e) => setHolder(e.target.value)}
                  className={inputCls}
                />
              </Field>
            </div>
            {!kyc.documents.pan?.verified && (
              <Button type="submit" disabled={busy}>Verify PAN</Button>
            )}
            {kyc.documents.pan?.verified && !kyc.documents.pan?.uploaded &&
              uploadField("pan", "PAN supporting document")}
          </form>

          <div className="space-y-4 rounded-lg border border-border/70 p-4">
            <h4 className="text-sm font-semibold">Aadhaar verification</h4>
            <p className="text-sm text-muted-foreground">
              Aadhaar is verified through DigiLocker. You will leave this site
              briefly and return here automatically.
            </p>
            {!kyc.documents.aadhaar?.verified ? (
              <Button type="button" disabled={busy} onClick={() => void act("aadhaar")}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Continue with DigiLocker
              </Button>
            ) : !kyc.documents.aadhaar?.uploaded ? (
              uploadField("aadhaar", "Aadhaar supporting document")
            ) : (
              <p className="text-sm text-emerald-600">Aadhaar verified and document received.</p>
            )}
          </div>

          {kyc.account_type === "business" && (
            <form
              className="space-y-4 rounded-lg border border-border/70 p-4"
              onSubmit={(e) => {
                e.preventDefault();
                void act("gst", { gst_number: gst });
              }}
            >
              <h4 className="text-sm font-semibold">GST verification</h4>
              <Field label="GSTIN">
                <Input
                  value={gst}
                  disabled={busy || kyc.documents.gst?.verified}
                  onChange={(e) => setGst(e.target.value.toUpperCase())}
                  className={inputCls}
                  placeholder={kyc.documents.gst?.verified ? "Verified" : "22AAAAA0000A1Z5"}
                />
              </Field>
              {!kyc.documents.gst?.verified && (
                <Button type="submit" disabled={busy}>Verify GSTIN</Button>
              )}
              {kyc.documents.gst?.verified && !kyc.documents.gst?.uploaded &&
                uploadField("gst", "GST supporting document")}
            </form>
          )}

          <div className="rounded-lg border border-border/70 p-4">
            <h4 className="text-sm font-semibold">Final submission</h4>
            {kyc.provider_complete ? (
              <p className="mt-2 text-sm leading-relaxed text-amber-700 dark:text-amber-400">
                Submitted to the verification provider. Number buying stays
                locked until the provider also marks this KYC
                <strong> Verified</strong>; use Refresh provider status to
                check again.
              </p>
            ) : kyc.ready_for_submission ? (
              kyc.final_submission_available ? (
                <>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    Your documents are complete, but final provider
                    acceptance is still pending. Buying unlocks only after
                    the status above becomes <strong>Verified</strong>.
                  </p>
                  <Button
                    type="button"
                    className="mt-3"
                    disabled={busy}
                    onClick={() => void act("submit")}
                  >
                    Submit verification
                  </Button>
                </>
              ) : (
                <p className="mt-2 text-sm leading-relaxed text-amber-700 dark:text-amber-400">
                  All steps are saved. Final submission is waiting for the
                  provider to confirm its client-scoped final-submit contract;
                  support will enable it without you redoing these steps.
                </p>
              )
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                Finish every verification and supporting document above to
                enable final submission.
              </p>
            )}
          </div>
        </div>
      )}

      <details className="rounded-lg border border-border/70 p-4">
        <summary className="cursor-pointer text-sm font-medium">
          Confirm email with a code, if requested
        </summary>
        <div className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">
            If you received an email-confirmation link, use that link instead.
            No provider password is needed here.
          </p>
          <Field label="Email verification code">
            <Input
              value={otp}
              maxLength={6}
              inputMode="numeric"
              disabled={busy}
              onChange={(e) => setOtp(e.target.value.replace(/[^0-9]/g, ""))}
              className={inputCls}
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={busy || otp.length !== 6}
              onClick={() => void act("verify_email", { otp })}
            >
              Confirm email
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void act("resend_email")}
            >
              Send new code
            </Button>
          </div>
        </div>
      </details>
    </section>
  );
}
