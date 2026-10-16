"use client";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api, keyStore } from "../api";

type Project = { id: number; name: string; url: string; description: string; budget: number };

export default function ProjectsPage() {
  const key = useSyncExternalStore(keyStore.subscribe, keyStore.get, () => null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { setProjects(await api(null, "/projects")); } catch (e) { setErr(String(e)); }
  }, []);

  useEffect(() => {
    let live = true;
    void (async () => { await Promise.resolve(); if (live) await load(); })();
    return () => { live = false; };
  }, [load]);

  async function donate(e: FormEvent<HTMLFormElement>, p: Project) {
    e.preventDefault();
    const amount = Number(new FormData(e.currentTarget).get("amount"));
    try {
      await api(key, `/projects/${p.id}/donations`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ amount }) });
      setMsg(`Donated ${amount} test credits to ${p.name}. Donations are irrevocable.`);
      setErr("");
      await load();
    } catch (e) { setErr(String(e)); }
  }

  async function propose(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      await api(key, "/projects", { method: "POST",
        body: JSON.stringify({ name: f.get("name"), url: f.get("url"), description: f.get("description") }) });
      setMsg("Submitted. It is listed once a moderator verifies it.");
      setErr("");
    } catch (e) { setErr(String(e)); }
  }

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: 16 }}>
      <h1>Open-source projects</h1>
      <p><Link href="/">Back to dashboard</Link>. Verified projects and the test credits donated to them. Credits have no cash value.</p>
      {err && <p role="alert" style={{ color: "crimson" }}>{err}</p>}
      {msg && <p role="status">{msg}</p>}
      {projects.length === 0 && <p>No verified projects yet.</p>}
      <ul>{projects.map((p) => (
        <li key={p.id}>
          <strong>{p.name}</strong> (<a href={p.url} rel="noopener noreferrer">{p.url}</a>): budget {p.budget} credits
          <div>{p.description}</div>
          {key && <form onSubmit={(e) => donate(e, p)}>
            <input name="amount" aria-label={`Credits to donate to ${p.name}`} type="number" min={1} required />{" "}
            <button>Donate</button>
          </form>}
        </li>))}
      </ul>
      {key ? <>
        <h2>Propose a project</h2>
        <form onSubmit={propose} style={{ display: "grid", gap: 8 }}>
          <input name="name" aria-label="Project name" placeholder="name" maxLength={100} required />
          <input name="url" aria-label="Project URL" placeholder="https://..." type="url" pattern="https://.*" required />
          <textarea name="description" aria-label="Description" placeholder="what the credits would fund" maxLength={1000} required />
          <button>Submit for review</button>
        </form>
      </> : <p>Log in on the dashboard to donate or propose a project.</p>}
    </main>
  );
}
