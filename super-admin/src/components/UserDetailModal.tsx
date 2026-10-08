"use client";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { StateBox, useBusy } from "@/components/PageHeader";
import {
  getUserDetail, setUserRole, setUserDisabled, adjustWallet,
  type ApiUser, type UserDetail,
} from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtINR } from "@/lib/format";

export default function UserDetailModal({
  user,
  onClose,
  onChanged,
}: {
  user: ApiUser;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { busy, msg, err, run } = useBusy();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getUserDetail(user.id)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user.id]);

  useEffect(load, [load]);

  const act = (fn: () => Promise<unknown>, okMsg: string) =>
    run(async () => {
      await fn();
      load();
      onChanged();
    }, okMsg);

  const isAdmin = detail?.user.role === "SUPER_ADMIN";
  const isDisabled = detail?.user.disabled ?? user.disabled ?? false;
  const usage = detail?.usage;

  return (
    <Modal title={`User — ${user.email}`} onClose={onClose} wide>
      <StateBox loading={loading} error={error}>
        {detail && (
          <div className="space-y-4 text-sm">
            {(msg || err) && (
              <div className={`p-3 rounded-xl text-xs ${msg ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-red-500/10 border border-red-500/30 text-red-300"}`}>
                {msg || err}
              </div>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <MiniStat label="Role" value={detail.user.role ?? "USER"} accent={isAdmin ? "text-purple-300" : undefined} />
              <MiniStat label="Status" value={isDisabled ? "Disabled" : "Active"} accent={isDisabled ? "text-red-300" : "text-emerald-300"} />
              <MiniStat label="Wallet" value={fmtINR(detail.user.wallet_balance)} accent="text-emerald-300" />
              <MiniStat label="Joined" value={fmtDateTime(detail.user.created_at)} />
            </div>

            {usage && (
              <div className="card p-4">
                <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase tracking-wider">Usage</h3>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <MiniStat label="Calls" value={usage.totalCallsCount} />
                  <MiniStat label="Talk time" value={fmtDuration(usage.totalMinutesUsed * 60)} />
                  <MiniStat label="Month spend" value={fmtINR(usage.currentMonthSpend)} />
                  <MiniStat label="Tokens (in/out)" value={`${usage.llmInputTokens} / ${usage.llmOutputTokens}`} />
                </div>
              </div>
            )}

            <div className="card p-4">
              <h3 className="text-xs font-bold text-gray-400 mb-3 uppercase tracking-wider">Admin actions</h3>
              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  className="btn-secondary text-xs"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(
                      isAdmin
                        ? `Demote ${user.email} to USER?`
                        : `Promote ${user.email} to SUPER_ADMIN? They get full platform control.`
                    )) {
                      act(() => setUserRole(user.id, isAdmin ? "USER" : "SUPER_ADMIN"), "Role updated ✓");
                    }
                  }}
                >
                  {isAdmin ? "⬇ Demote to USER" : "⬆ Promote to SUPER_ADMIN"}
                </button>
                <button
                  className={isDisabled ? "btn-secondary text-xs" : "btn-danger text-xs"}
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(
                      isDisabled ? `Enable ${user.email}?` : `Disable ${user.email}? They will be logged out and blocked from the API.`
                    )) {
                      act(() => setUserDisabled(user.id, !isDisabled), isDisabled ? "User enabled ✓" : "User disabled ✓");
                    }
                  }}
                >
                  {isDisabled ? "✓ Enable account" : "⛔ Disable account"}
                </button>
              </div>

              <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase tracking-wider">Wallet adjustment (₹)</h3>
              <div className="flex flex-wrap gap-2">
                <input
                  className="input w-32"
                  type="number"
                  step="0.01"
                  placeholder="+100 or -50"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
                <input
                  className="input flex-1 min-w-40"
                  placeholder="Reason (required, goes to audit log)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <button
                  className="btn text-xs"
                  disabled={busy || !amount || !note.trim()}
                  onClick={() => {
                    if (window.confirm(`Adjust ${user.email}'s wallet by ₹${amount}?`)) {
                      act(async () => {
                        await adjustWallet(user.id, Number(amount), note.trim());
                        setAmount("");
                        setNote("");
                      }, "Wallet adjusted ✓");
                    }
                  }}
                >
                  Apply
                </button>
              </div>
              <p className="text-[10px] text-gray-600 mt-2">
                Positive adds credit, negative deducts. Every change is written to the audit log.
              </p>
            </div>

            {detail.wallet.transactions.length > 0 && (
              <div className="card p-4">
                <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase tracking-wider">Recent transactions</h3>
                <div className="max-h-40 overflow-y-auto custom-scrollbar space-y-1.5">
                  {detail.wallet.transactions.slice(0, 15).map((t, i) => (
                    <div key={i} className="flex items-center justify-between text-xs border-b border-gray-800/60 pb-1.5">
                      <span className="text-gray-400">{fmtDateTime(String((t as Record<string, unknown>).ts ?? ""))}</span>
                      <span className={`font-mono ${Number((t as Record<string, unknown>).amount ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                        {fmtINR(Number((t as Record<string, unknown>).amount ?? 0))}
                      </span>
                      <span className="text-gray-500 truncate max-w-45">{String((t as Record<string, unknown>).note ?? "")}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </StateBox>
    </Modal>
  );
}

function MiniStat({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-xl bg-gray-800/50 border border-gray-800 px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-sm font-bold mt-0.5 ${accent || "text-white"}`}>{value}</div>
    </div>
  );
}
