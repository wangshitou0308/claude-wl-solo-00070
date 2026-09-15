import type { Layout, SessionView, StepT } from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = j.detail || msg;
    } catch {
      /* keep */
    }
    throw new Error(msg);
  }
  return r.json();
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  getLayout: () => req<Layout>("/layout"),
  putLayout: (l: Layout) =>
    req<Layout>("/layout", { method: "PUT", ...json(l) }),
  seedDemo: () => req<Layout>("/demo/seed", { method: "POST" }),

  activeSession: () => req<SessionView>("/sessions/active"),
  createSession: (flow_lpm: number) =>
    req<SessionView>("/sessions", { method: "POST", ...json({ flow_lpm }) }),
  confirm: (sid: string, step_id: string) =>
    req<SessionView>(`/sessions/${sid}/confirm`, {
      method: "POST", ...json({ step_id }),
    }),
  issue: (sid: string, furrow_id: string, kind: string, note = "") =>
    req<SessionView>(`/sessions/${sid}/issue`, {
      method: "POST", ...json({ furrow_id, kind, note }),
    }),
  undo: (sid: string) =>
    req<SessionView>(`/sessions/${sid}/undo`, { method: "POST" }),
  setRoute: (sid: string, stepId: string, points: [number, number][]) =>
    req<SessionView>(`/sessions/${sid}/steps/${stepId}/route`, {
      method: "POST", ...json({ points }),
    }),
  abort: (sid: string) =>
    req<{ ok: boolean }>(`/sessions/${sid}/abort`, { method: "POST" }),
};
