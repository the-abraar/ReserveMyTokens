"""OIDC login. The coordinator accepts an RS256 ID token from OIDC_ISSUER as a bearer token, checks it against the
issuer's JWKS, and maps (iss, sub) to a user. For local dev, `stub` is a minimal issuer (authorization code + PKCE)
that stands in for the managed provider; it answers 404 unless OIDC_STUB=1 and RMT_ENV=dev."""
import base64
import hashlib
import html
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def issuer() -> str | None:
    """Fail closed: a plain-http issuer is accepted only in dev."""
    iss = os.getenv("OIDC_ISSUER")
    if iss and not iss.startswith("https://") and not is_dev():
        return None
    return iss


def audience() -> str:
    return os.getenv("OIDC_AUDIENCE", "rmt-web")


def is_dev() -> bool:
    return os.getenv("RMT_ENV") == "dev"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:  # URL comes from operator config, not the caller
        return json.load(r)


@lru_cache(maxsize=4)
def _keys(iss: str, hour: int) -> jwt.PyJWKSet:
    """JWKS, refetched at most once per hour (the `hour` arg is the cache key), so a caller cannot force refetches."""
    conf = _get_json(f"{iss}/.well-known/openid-configuration")
    if conf.get("issuer") != iss:
        raise jwt.InvalidIssuerError("discovery issuer mismatch")
    return jwt.PyJWKSet.from_dict(_get_json(conf["jwks_uri"]))


def verify(token: str) -> dict:
    """Claims of a valid ID token; raises jwt.PyJWTError (or OSError if the issuer is unreachable) otherwise."""
    iss = issuer()
    if not iss:
        raise jwt.InvalidTokenError("OIDC not configured")
    kid = jwt.get_unverified_header(token).get("kid")
    key = next((k for k in _keys(iss, int(time.time() // 3600)).keys if k.key_id == kid), None)
    if key is None:
        raise jwt.InvalidTokenError("unknown signing key")
    return jwt.decode(token, key.key, algorithms=["RS256"], audience=audience(), issuer=iss,
                      options={"require": ["exp", "iat", "sub", "iss", "aud"]})


# ---- dev-only stub issuer -------------------------------------------------------------------------------------------
# Auth: none on these routes, deliberately: this IS the identity provider (dev only, 404 otherwise).
stub = APIRouter(prefix="/oidc-stub")
_codes: dict[str, dict] = {}  # shortcut: in-memory, single process; the stub is for local dev only


@lru_cache(maxsize=1)
def _stub_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)  # new key per process start


def _stub_iss() -> str:
    if os.getenv("OIDC_STUB") != "1" or not is_dev() or not os.getenv("OIDC_ISSUER"):
        raise HTTPException(404, "not found")
    return os.environ["OIDC_ISSUER"]


def _local(uri: str) -> bool:
    u = urllib.parse.urlsplit(uri)
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


async def _form(request: Request) -> dict[str, str]:
    body = (await request.body())[:10000].decode(errors="replace")
    return {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}


@stub.get("/.well-known/openid-configuration")
def discovery():
    iss = _stub_iss()
    return {"issuer": iss, "authorization_endpoint": f"{iss}/authorize", "token_endpoint": f"{iss}/token",
            "jwks_uri": f"{iss}/jwks", "response_types_supported": ["code"], "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]}


@stub.get("/jwks")
def jwks():
    _stub_iss()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_stub_key().public_key()))
    return {"keys": [{**jwk, "kid": "stub-1", "alg": "RS256", "use": "sig"}]}


_AUTH_FIELDS = ("client_id", "redirect_uri", "state", "nonce", "code_challenge")


@stub.get("/authorize", response_class=HTMLResponse)
def authorize_form(request: Request):
    _stub_iss()
    q = request.query_params
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        raise HTTPException(400, "code flow with PKCE S256 required")
    if not _local(q.get("redirect_uri", "")):
        raise HTTPException(400, "stub accepts only http://localhost redirect URIs")
    hidden = "".join(f'<input type="hidden" name="{f}" value="{html.escape(q.get(f, ""), quote=True)}">' for f in _AUTH_FIELDS)
    return (f'<!doctype html><title>Dev login (stub)</title><h1>Dev OIDC stub</h1><p>Not a real identity provider.</p>'
            f'<form method="post"><label>Username <input name="username" required maxlength="64"></label>{hidden}'
            f'<button>Sign in</button></form>')


@stub.post("/authorize")
async def authorize_submit(request: Request):
    _stub_iss()
    f = await _form(request)
    user = f.get("username", "").strip()
    if not 1 <= len(user) <= 64 or not _local(f.get("redirect_uri", "")) or not f.get("code_challenge"):
        raise HTTPException(400, "bad request")
    code = secrets.token_urlsafe(24)
    _codes[code] = {**{k: f.get(k, "") for k in _AUTH_FIELDS}, "sub": f"stub|{user}", "exp": time.time() + 60}
    qs = urllib.parse.urlencode({"code": code, "state": f.get("state", "")})
    return RedirectResponse(f"{f['redirect_uri']}{'&' if '?' in f['redirect_uri'] else '?'}{qs}", status_code=303)


@stub.post("/token")
async def token(request: Request):
    iss = _stub_iss()
    f = await _form(request)
    c = _codes.pop(f.get("code", ""), None)  # single use
    challenge = _b64url(hashlib.sha256(f.get("code_verifier", "").encode()).digest())
    if (not c or c["exp"] < time.time() or f.get("grant_type") != "authorization_code" or c["client_id"] != f.get("client_id")
            or c["redirect_uri"] != f.get("redirect_uri") or not secrets.compare_digest(challenge, c["code_challenge"])):
        raise HTTPException(400, "invalid_grant")
    t = int(time.time())
    claims = {"iss": iss, "sub": c["sub"], "aud": c["client_id"], "iat": t, "exp": t + 3600, "nonce": c["nonce"],
              "preferred_username": c["sub"].removeprefix("stub|")}
    tok = jwt.encode(claims, _stub_key(), algorithm="RS256", headers={"kid": "stub-1"})
    return {"id_token": tok, "token_type": "Bearer", "expires_in": 3600}
