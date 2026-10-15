import type { DeskState, Profile, StrategyInfo } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `No se pudo conectar con el backend en ${API_URL}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  state: (t: string) => request<DeskState>(t, "/api/state"),
  replay: (t: string) => request<Record<string, number>>(t, "/api/sim/replay", { method: "POST" }),
  reset: (t: string) => request<unknown>(t, "/api/sim/reset", { method: "POST" }),
  flatten: (t: string) => request<unknown>(t, "/api/flatten", { method: "POST" }),
  updateStrategy: (t: string, id: string, body: { enabled?: boolean; symbols?: string[]; params?: Record<string, unknown> }) =>
    request<StrategyInfo>(t, `/api/strategies/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  updateProfile: (t: string, changes: Partial<Profile>) =>
    request<Profile>(t, "/api/risk/profile", { method: "PUT", body: JSON.stringify({ changes }) }),
};

/**
 * SSE over fetch so the token travels in the Authorization header (EventSource cannot set headers).
 * Calls onMessage for every data frame; reconnects with backoff until aborted.
 */
export function openStream(token: string, onMessage: (msg: { type: string }) => void, onStatus: (ok: boolean) => void) {
  const ctrl = new AbortController();
  let delay = 1000;
  const run = async () => {
    while (!ctrl.signal.aborted) {
      try {
        const res = await fetch(`${API_URL}/api/stream`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        onStatus(true);
        delay = 1000;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const data = frame
              .split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).trim())
              .join("");
            if (data) {
              try {
                onMessage(JSON.parse(data));
              } catch {
                /* ignore malformed frame */
              }
            }
          }
        }
      } catch {
        if (ctrl.signal.aborted) return;
      }
      onStatus(false);
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 15000);
    }
  };
  void run();
  return () => ctrl.abort();
}
