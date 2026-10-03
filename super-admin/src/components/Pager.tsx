"use client";

export default function Pager({
  total,
  page,
  pageSize,
  onPage,
}: {
  total: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between mt-3 text-xs text-gray-500">
      <span>
        {total} total · page {page} of {pages}
      </span>
      <div className="flex gap-2">
        <button
          className="btn-secondary text-xs px-2.5 py-1"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          ← Prev
        </button>
        <button
          className="btn-secondary text-xs px-2.5 py-1"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
