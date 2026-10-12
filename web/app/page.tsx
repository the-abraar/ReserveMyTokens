"use client";
import { FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Job = { id: number; status: string; model: string; max_tokens: number; output: string | null };
type Worker = { id: number; name: string; revoked: boolean };

// sessionStorage as an external store: read on the client, null during server render.
const keyStore = {
  get: () => { try { return sessionStorage.getItem("rmt_key"); } catch { return null; } },
  subscribe: (cb: () => void) => { window.addEventListener("rmt-key", cb); return () => window.removeEventListener("rmt-key", cb); },
  set: (v: string | null) => {
    try { if (v) sessionStorage.setItem("rmt_key", v); else sessionStorage.removeItem("rmt_key"); } catch { /* storage blocked: key stays in memory only for this call */ }
    window.dispatchEvent(new Event("rmt-key"));
  },
};

export default function Home() {
  const key = useSyncExternalStore(keyStore.subscribe, keyStore.get, () => null);
  const [draft, setDraft] = useState("");
  const [bal, setBal] = useState<{ available: number; held: number } | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [err, setErr] = useState("");

  const call = useCallback(async (path: string, init?: RequestInit) => {
    const r = await fetch(API + path, { ...init, headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" } });
    if (!r.ok) throw new Error(`${r.status} ${(await r.json().catch(() => ({}))).detail ?? ""}`);
    return r.json();
  }, [key]);

  const refresh = useCallback(async () => {
    try {
      setBal(await call("/users/me/balance"));
      setJobs(await call("/jobs"));
      setWorkers(await call("/workers"));
      setErr("");
    } catch (e) { setErr(String(e)); }
  }, [call]);

  // shortcut: key lives in sessionStorage (cleared with the tab); no refresh token or server session.
  useEffect(() => {
    if (!key) return;
    let live = true;
    void (async () => { await Promise.resolve(); if (live) await refresh(); })();
    return () => { live = false; };
  }, [key, refresh]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      await call("/jobs", { method: "POST", body: JSON.stringify({ model: f.get("model"), prompt: f.get("prompt"), max_tokens: Number(f.get("max_tokens")) }) });
      await refresh();
    } catch (e) { setErr(String(e)); }
  }

  if (!key) return (
    <main style={{ maxWidth: 480, margin: "4rem auto", padding: 16 }}>
      <h1>ReserveMyTokens</h1>
      <p>Test credits only. Log in with your API key.</p>
      <form onSubmit={(e) => { e.preventDefault(); keyStore.set(draft); }}>
        <input type="password" aria-label="API key" value={draft} onChange={(e) => setDraft(e.target.value)} required style={{ width: "100%" }} />
        <button>Log in</button>
      </form>
    </main>
  );

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: 16 }}>
      <h1>ReserveMyTokens</h1>
      <button onClick={() => { keyStore.set(null); }}>Log out</button>{" "}
      <button onClick={refresh}>Refresh</button>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      <h2>Balance</h2>
      <p>{bal ? `${bal.available} available, ${bal.held} held (test credits)` : "..."}</p>
      <h2>Submit job</h2>
      <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
        <input name="model" placeholder="model" required />
        <textarea name="prompt" placeholder="prompt" required />
        <input name="max_tokens" type="number" min={1} max={4096} defaultValue={100} required />
        <button>Submit</button>
      </form>
      <h2>Jobs</h2>
      <ul>{jobs.map((j) => <li key={j.id}>#{j.id} {j.model} [{j.status}] {j.output ?? ""}</li>)}</ul>
      <h2>Workers</h2>
      <ul>{workers.map((w) => <li key={w.id}>#{w.id} {w.name}{w.revoked ? " (revoked)" : ""}</li>)}</ul>
    </main>
  );
}
