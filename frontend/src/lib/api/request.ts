// Shared fetch core for the api package (request/response handling lives
// here so index.ts + subs.ts stay small — ≤300-line rule).
//
// Auth: httpOnly cookie session (`credentials: "include"` on every call).
// Fetch optimisation: cachedReq() gives read endpoints an in-memory,
// TTL-scoped cache with in-flight request de-duplication (a burst of
// widgets mounting together issues ONE network call, not N). Mutations
// call invalidate() for the affected resource prefix.

// Backend base URL (FastAPI on :8000). Override with NEXT_PUBLIC_BACKEND_URL.
export const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* ignore */
    }
    throw Object.assign(new Error(detail || `Request failed (${res.status})`), {
      status: res.status,
    });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ---- cached GET with TTL + in-flight de-dup --------------------------------
type Entry = { data: unknown; ts: number };
const _cache = new Map<string, Entry>();
const _inflight = new Map<string, Promise<unknown>>();

export function invalidate(prefix: string): void {
  // es5 target: iterate a copy, not the live MapIterator.
  for (const k of Array.from(_cache.keys())) if (k.startsWith(prefix)) _cache.delete(k);
  // In-flight fetches are left to finish; their resolution simply isn't cached again here.
}

export async function cachedReq<T>(path: string, ttlMs = 30_000): Promise<T> {
  const hit = _cache.get(path);
  if (hit && Date.now() - hit.ts < ttlMs) return hit.data as T;
  const pending = _inflight.get(path);
  if (pending) return pending as Promise<T>;
  const p = req<T>(path)
    .then((data) => {
      _cache.set(path, { data, ts: Date.now() });
      _inflight.delete(path);
      return data;
    })
    .catch((e) => {
      _inflight.delete(path);
      throw e;
    });
  _inflight.set(path, p);
  return p;
}
