// Shared by the dashboard pages: API base, the session key store, and OIDC login (authorization code + PKCE).
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const OIDC_ISSUER = process.env.NEXT_PUBLIC_OIDC_ISSUER ?? "";
const CLIENT_ID = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "rmt-web";

// sessionStorage as an external store: read on the client, null during server render.
// The value is an API key or an OIDC ID token; the coordinator accepts either as a bearer token.
export const keyStore = {
  get: () => { try { return sessionStorage.getItem("rmt_key"); } catch { return null; } },
  subscribe: (cb: () => void) => { window.addEventListener("rmt-key", cb); return () => window.removeEventListener("rmt-key", cb); },
  set: (v: string | null) => {
    try { if (v) sessionStorage.setItem("rmt_key", v); else sessionStorage.removeItem("rmt_key"); } catch { /* storage blocked: key stays in memory only for this call */ }
    window.dispatchEvent(new Event("rmt-key"));
  },
};

export async function api(key: string | null, path: string, init?: RequestInit) {
  const headers = { "Content-Type": "application/json", ...(key ? { Authorization: `Bearer ${key}` } : {}), ...init?.headers };
  const r = await fetch(API + path, { ...init, headers });
  if (!r.ok) throw new Error(`${r.status} ${(await r.json().catch(() => ({}))).detail ?? ""}`);
  return r.status === 204 ? null : r.json();
}

const b64url = (b: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const random = () => b64url(crypto.getRandomValues(new Uint8Array(32)));
const redirectUri = () => `${location.origin}/`;

async function discover(): Promise<{ authorization_endpoint: string; token_endpoint: string }> {
  const r = await fetch(`${OIDC_ISSUER}/.well-known/openid-configuration`);
  if (!r.ok) throw new Error(`OIDC discovery failed: ${r.status}`);
  return r.json();
}

export async function startOidcLogin() {
  const conf = await discover();
  const verifier = random(), state = random(), nonce = random();
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  sessionStorage.setItem("rmt_oidc", JSON.stringify({ verifier, state, nonce }));
  const q = new URLSearchParams({ response_type: "code", client_id: CLIENT_ID, redirect_uri: redirectUri(), scope: "openid",
    state, nonce, code_challenge: challenge, code_challenge_method: "S256" });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- external identity provider, not a Next route
  location.assign(`${conf.authorization_endpoint}?${q}`);
}

/** On the redirect back: exchange the code for an ID token. Null when this page load is not a login callback.
 * shortcut: no refresh token; the ID token expires (1 h on the stub) and the user logs in again. */
export async function finishOidcLogin(): Promise<string | null> {
  const p = new URLSearchParams(location.search);
  const code = p.get("code");
  if (!code) return null;
  const saved = JSON.parse(sessionStorage.getItem("rmt_oidc") ?? "null");
  sessionStorage.removeItem("rmt_oidc");
  history.replaceState(null, "", location.pathname);
  if (!saved || p.get("state") !== saved.state) throw new Error("login state mismatch");
  const r = await fetch((await discover()).token_endpoint, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", code, client_id: CLIENT_ID, redirect_uri: redirectUri(),
      code_verifier: saved.verifier }),
  });
  if (!r.ok) throw new Error(`token exchange failed: ${r.status}`);
  const { id_token } = await r.json();
  // The coordinator verifies the signature; the browser only checks this token answers its own request.
  const claims = JSON.parse(atob(id_token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  if (claims.nonce !== saved.nonce) throw new Error("login nonce mismatch");
  return id_token;
}
