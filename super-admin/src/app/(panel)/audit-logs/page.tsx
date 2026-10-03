"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox } from "@/components/PageHeader";
import Pager from "@/components/Pager";
import { listAuditLogs, type AuditLog, type Paged } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

// Matches the exact action strings written by backend/app/services via audit().
const ACTION_PILL: Record<string, string> = {
  user_role_super_admin: "pill pill-purple",
  user_role_user: "pill pill-gray",
  user_disabled: "pill pill-red",
  user_enabled: "pill pill-green",
  wallet_adjusted: "pill pill-green",
  provider_created: "pill pill-blue",
  provider_updated: "pill pill-blue",
  provider_deleted: "pill pill-red",
  model_created: "pill pill-blue",
  model_updated: "pill pill-amber",
  model_deleted: "pill pill-red",
  api_key_created: "pill pill-amber",
  api_key_rotated: "pill pill-amber",
  api_key_updated: "pill pill-gray",
  billing_config_changed: "pill pill-green",
};

export default function AuditLogsPage() {
  const [data, setData] = useState<Paged<AuditLog> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [targetType, setTargetType] = useState("");
  const [pageL, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listAuditLogs({
      page: pageL,
      page_size: 50,
      q: q || undefined,
      target_type: targetType || undefined,
    })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [pageL, q, targetType]);

  useEffect(load, [load]);

  return (
    <>
      <PageHeader title="Audit logs" subtitle="Every admin mutation — who, what, when" />

      <div className="card p-3 mb-4 flex flex-wrap items-center gap-2">
        <input
          className="input flex-1 min-w-52"
          placeholder="Search admin, action, or target…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          className="input w-44"
          value={targetType}
          onChange={(e) => {
            setTargetType(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All target types</option>
          <option value="user">user</option>
          <option value="provider">provider</option>
          <option value="model">model</option>
          <option value="credential">credential</option>
          <option value="billing">billing</option>
        </select>
      </div>

      <StateBox loading={loading} error={error} empty={data && data.items.length === 0 ? "No audit entries yet — they appear after the first admin action." : null}>
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Admin</th>
                <th>Action</th>
                <th>Target</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((l) => (
                <tr key={l.id} className="align-top">
                  <td className="text-gray-400 text-xs whitespace-nowrap">{fmtDateTime(l.created_at)}</td>
                  <td className="text-gray-300 text-xs">{l.admin_email || "—"}</td>
                  <td>
                    <span className={ACTION_PILL[l.action] || "pill pill-gray"}>{l.action}</span>
                  </td>
                  <td className="text-xs">
                    <span className="text-gray-400">{l.target_type}</span>{" "}
                    <span className="font-mono text-gray-500">{l.target_id.slice(0, 12)}{l.target_id.length > 12 ? "…" : ""}</span>
                  </td>
                  <td>
                    {Object.keys(l.detail || {}).length > 0 && (
                      <button
                        className="btn-secondary text-xs px-2.5 py-1"
                        onClick={() => setExpanded(expanded === l.id ? null : l.id)}
                      >
                        {expanded === l.id ? "Hide" : "Detail"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {expanded && data && (
          <div className="card p-4 mt-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">Change detail</div>
            <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">
              {JSON.stringify(data.items.find((l) => l.id === expanded)?.detail ?? {}, null, 2)}
            </pre>
          </div>
        )}
        {data && <Pager total={data.total} page={data.page} pageSize={data.page_size} onPage={setPage} />}
      </StateBox>
    </>
  );
}
