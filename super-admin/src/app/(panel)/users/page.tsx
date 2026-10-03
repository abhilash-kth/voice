"use client";
import { useCallback, useEffect, useState } from "react";
import PageHeader, { StateBox } from "@/components/PageHeader";
import Pager from "@/components/Pager";
import UserDetailModal from "@/components/UserDetailModal";
import { listUsers, type ApiUser, type Paged } from "@/lib/api";
import { fmtDateTime, fmtINR } from "@/lib/format";

export default function UsersPage() {
  const [data, setData] = useState<Paged<ApiUser> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [pageL, setPage] = useState(1);
  const [selected, setSelected] = useState<ApiUser | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listUsers({
      page: pageL,
      page_size: 25,
      q: q || undefined,
      role: role || undefined,
      disabled: status === "" ? undefined : status === "disabled",
    })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [pageL, q, role, status]);

  useEffect(load, [load]);

  return (
    <>
      <PageHeader title="Users" subtitle="Every registered account — roles, access, wallets" />

      <div className="card p-3 mb-4 flex flex-wrap items-center gap-2">
        <input
          className="input flex-1 min-w-52"
          placeholder="Search by email or name…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          className="input w-40"
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All roles</option>
          <option value="USER">USER</option>
          <option value="SUPER_ADMIN">SUPER_ADMIN</option>
        </select>
        <select
          className="input w-36"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>

      <StateBox
        loading={loading}
        error={error}
        empty={data && data.items.length === 0 ? "No users match these filters." : null}
      >
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th className="text-right">Wallet</th>
                <th>Joined</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="font-semibold text-gray-100">{u.name || "—"}</div>
                    <div className="text-[11px] text-gray-500">{u.email}</div>
                  </td>
                  <td>
                    {u.role === "SUPER_ADMIN" ? (
                      <span className="pill pill-purple">SUPER_ADMIN</span>
                    ) : (
                      <span className="pill pill-gray">USER</span>
                    )}
                  </td>
                  <td>
                    {u.disabled ? (
                      <span className="pill pill-red">● disabled</span>
                    ) : (
                      <span className="pill pill-green">● active</span>
                    )}
                  </td>
                  <td className="text-right font-semibold text-emerald-300">
                    {fmtINR(u.wallet_balance)}
                  </td>
                  <td className="text-gray-500 text-xs">{fmtDateTime(u.created_at)}</td>
                  <td>
                    <button className="btn-secondary text-xs px-2.5 py-1" onClick={() => setSelected(u)}>
                      Manage
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && (
          <Pager total={data.total} page={data.page} pageSize={data.page_size} onPage={setPage} />
        )}
      </StateBox>

      {selected && (
        <UserDetailModal
          user={selected}
          onClose={() => setSelected(null)}
          onChanged={load}
        />
      )}
    </>
  );
}
