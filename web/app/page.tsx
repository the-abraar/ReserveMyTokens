"use client";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { OIDC_ISSUER, api, finishOidcLogin, keyStore, startOidcLogin } from "./api";

type Job = { id: number; status: string; model: string; max_tokens: number; output: string | null };
type Worker = { id: number; name: string; revoked: boolean; online: boolean; last_seen_at: string | null; models: string[];
  signing_key: boolean; jobs_settled: number };
type Receipt = { job_id: number; worker_id: number; prompt_tokens: number; completion_tokens: number; charged: number;
  signed: boolean; usage_source: string };
const PENDING = ["queued", "leased"];

export default function Home() {
  const key = useSyncExternalStore(keyStore.subscribe, keyStore.get, () => null);
  const [draft, setDraft] = useState("");
  const [bal, setBal] = useState<{ available: number; held: number } | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [receipts, setReceipts] = useState<Record<number, Receipt>>({});
  const [estimate, setEstimate] = useState("");
  const [err, setErr] = useState("");
  const [newToken, setNewToken] = useState("");

  const call = useCallback((path: string, init?: RequestInit) => api(key, path, init), [key]);

  const refresh = useCallback(async () => {
    try {
      setBal(await call("/users/me/balance"));
      setJobs(await call("/jobs"));
      setWorkers(await call("/workers"));
      setErr("");
    } catch (e) { setErr(String(e)); }
  }, [call]);

  // OIDC redirect back: finish the code exchange once, on load.
  useEffect(() => {
    void finishOidcLogin().then((t) => { if (t) keyStore.set(t); }, (e) => setErr(String(e)));
  }, []);

  // shortcut: key lives in sessionStorage (cleared with the tab); no refresh token or server session.
  useEffect(() => {
    if (!key) return;
    let live = true;
    void (async () => { await Promise.resolve(); if (live) await refresh(); })();
    return () => { live = false; };
  }, [key, refresh]);

  // Poll while a job is still running so its output appears without a manual refresh.
  const pending = jobs.some((j) => PENDING.includes(j.status));
  useEffect(() => {
    if (!key || !pending) return;
    const t = setInterval(() => void refresh(), 3000);
    return () => clearInterval(t);
  }, [key, pending, refresh]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      await call("/jobs", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ model: f.get("model"), prompt: f.get("prompt"), max_tokens: Number(f.get("max_tokens")) }) });
      await refresh();
    } catch (e) { setErr(String(e)); }
  }

  async function estimateCost(form: HTMLFormElement | null) {
    if (!form) return;
    const f = new FormData(form);
    try {
      const q = new URLSearchParams({ model: String(f.get("model")), max_tokens: String(f.get("max_tokens")) });
      const r = await call(`/estimate?${q}`);
      setEstimate(`At most ${r.max_charge} credits (unused tokens are refunded). ${r.online_workers} online worker(s) offer this model.`);
    } catch (e) { setErr(String(e)); }
  }

  async function showReceipt(id: number) {
    try { const r = await call(`/jobs/${id}/receipt`); setReceipts((m) => ({ ...m, [id]: r })); } catch (e) { setErr(String(e)); }
  }

  async function addWorker(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      const w = await call("/workers", { method: "POST", body: JSON.stringify({ name: new FormData(e.currentTarget).get("name") }) });
      setNewToken(`Worker #${w.id} token (shown once, copy it now, then run: rmt-worker login --worker-id ${w.id}): ${w.token}`);
      await refresh();
    } catch (e) { setErr(String(e)); }
  }

  async function revoke(id: number) {
    try { await call(`/workers/${id}`, { method: "DELETE" }); await refresh(); } catch (e) { setErr(String(e)); }
  }

  if (!key) return (
    <main style={{ maxWidth: 480, margin: "4rem auto", padding: 16 }}>
      <h1>ReserveMyTokens</h1>
      <p>Test credits only.</p>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      {OIDC_ISSUER && <p><button onClick={() => void startOidcLogin().catch((e) => setErr(String(e)))}>Log in with OIDC</button></p>}
      <form onSubmit={(e) => { e.preventDefault(); keyStore.set(draft); }}>
        <label>Or use an API key <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)} required style={{ width: "100%" }} /></label>
        <button>Log in</button>
      </form>
      <p><Link href="/projects">Open-source projects</Link></p>
    </main>
  );

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: 16 }}>
      <h1>ReserveMyTokens</h1>
      <button onClick={() => { keyStore.set(null); }}>Log out</button>{" "}
      <button onClick={refresh}>Refresh</button>{" "}
      <Link href="/projects">Projects and donations</Link>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      <h2>Balance</h2>
      <p>{bal ? `${bal.available} available, ${bal.held} held (test credits)` : "..."}</p>

      <h2>Submit job</h2>
      <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
        <input name="model" aria-label="Model" placeholder="model" required />
        <textarea name="prompt" aria-label="Prompt" placeholder="prompt" required />
        <input name="max_tokens" aria-label="Max tokens" type="number" min={1} max={4096} defaultValue={100} required />
        <div><button type="button" onClick={(e) => void estimateCost(e.currentTarget.form)}>Estimate cost</button>{" "}<button>Submit</button></div>
      </form>
      {estimate && <p role="status">{estimate}</p>}

      <h2>Jobs</h2>
      <ul>{jobs.map((j) => (
        <li key={j.id}>#{j.id} {j.model} [{j.status}] {j.output ?? ""}
          {j.status === "completed" && !receipts[j.id] && <> <button onClick={() => showReceipt(j.id)}>Receipt</button></>}
          {receipts[j.id] && <div><small>
            Receipt: worker #{receipts[j.id].worker_id}, {receipts[j.id].prompt_tokens} prompt + {receipts[j.id].completion_tokens} completion
            tokens ({receipts[j.id].usage_source}), charged {receipts[j.id].charged}, {receipts[j.id].signed ? "signed by the worker" : "unsigned"}
          </small></div>}
        </li>))}
      </ul>

      <h2>Workers</h2>
      <form onSubmit={addWorker}>
        <input name="name" aria-label="Worker name" placeholder="worker name" maxLength={64} required />{" "}
        <button>Register worker</button>
      </form>
      {newToken && <p role="status"><code>{newToken}</code></p>}
      <ul>{workers.map((w) => (
        <li key={w.id}>#{w.id} {w.name}{" "}
          {w.revoked ? "(revoked)" : <>[{w.online ? "online" : "offline"}] <button onClick={() => revoke(w.id)}>Revoke</button></>}
          <div><small>
            {w.models.length ? `models: ${w.models.join(", ")}; ` : ""}jobs settled: {w.jobs_settled};
            {" "}{w.signing_key ? "signing key registered" : "no signing key"}
            {w.last_seen_at ? `; last seen ${new Date(w.last_seen_at).toLocaleString()}` : "; never connected"}
          </small></div>
        </li>))}
      </ul>
    </main>
  );
}
