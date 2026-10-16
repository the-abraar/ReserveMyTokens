"""OIDC login through the dev stub issuer, verified by the coordinator against the stub's JWKS."""
import base64
import hashlib
import secrets
import urllib.parse

import jwt
import pytest
from app import oidc
from app.main import app
from fastapi.testclient import TestClient

c = TestClient(app)
ISS = "http://testserver/oidc-stub"
REDIRECT = "http://localhost:3000/"


def stub_login(client, username, client_id="rmt-web", verifier=None, base="", redirect_kw=None):
    """Authorization code + PKCE against the stub. Works with TestClient, or with requests given `base` and
    redirect_kw={"allow_redirects": False}."""
    v = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "st", "nonce": "nn",
         "code_challenge": challenge, "code_challenge_method": "S256"}
    iss = base
    assert client.get(f"{iss}/oidc-stub/authorize", params=q).status_code == 200
    r = client.post(f"{iss}/oidc-stub/authorize", data={**q, "username": username}, **(redirect_kw or {"follow_redirects": False}))
    loc = urllib.parse.urlsplit(r.headers["location"])
    code = urllib.parse.parse_qs(loc.query)["code"][0]
    assert loc.geturl().startswith(REDIRECT) and urllib.parse.parse_qs(loc.query)["state"] == ["st"]
    return client.post(f"{iss}/oidc-stub/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                                       "redirect_uri": REDIRECT, "code_verifier": verifier or v})


@pytest.fixture
def stub_on(monkeypatch):
    monkeypatch.setenv("RMT_ENV", "dev")
    monkeypatch.setenv("OIDC_STUB", "1")
    monkeypatch.setenv("OIDC_ISSUER", ISS)
    monkeypatch.setattr(oidc, "_get_json", lambda url: c.get(url).json())  # JWKS fetch through the test client
    oidc._keys.cache_clear()
    yield
    oidc._keys.cache_clear()


def H(t):
    return {"Authorization": f"Bearer {t}"}


def test_login_provisions_one_user_per_subject(stub_on):
    t1 = stub_login(c, "alice").json()["id_token"]
    t2 = stub_login(c, "alice").json()["id_token"]
    me1, me2 = c.get("/users/me", headers=H(t1)).json(), c.get("/users/me", headers=H(t2)).json()
    assert me1["id"] == me2["id"] and me1["oidc"] is True
    assert c.get("/users/me/balance", headers=H(t1)).json() == {"available": 0, "held": 0}
    bob = stub_login(c, "bob").json()["id_token"]
    assert c.get("/users/me", headers=H(bob)).json()["id"] != me1["id"]
    # an OIDC user can do everything an API-key user can, e.g. register a worker
    assert c.post("/workers", json={"name": "w"}, headers=H(t1)).status_code == 201


def test_bad_tokens_are_rejected(stub_on):
    good = stub_login(c, "alice").json()["id_token"]
    head, _, sig = good.split(".")
    claims = jwt.decode(good, options={"verify_signature": False})
    forged_body = base64.urlsafe_b64encode(f'{{"sub":"stub|admin","iss":"{ISS}"}}'.encode()).rstrip(b"=").decode()
    other_aud = stub_login(c, "alice", client_id="someone-else").json()["id_token"]
    unsigned = jwt.encode({**claims, "sub": "stub|x"}, key=None, algorithm="none")
    for bad in (f"{head}.{forged_body}.{sig}", other_aud, unsigned, "a.b.c"):
        assert c.get("/users/me", headers=H(bad)).status_code == 401, bad


def test_pkce_and_single_use_code(stub_on):
    assert stub_login(c, "alice", verifier="wrong-verifier").status_code == 400
    v = secrets.token_urlsafe(32)
    ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    q = {"client_id": "rmt-web", "redirect_uri": REDIRECT, "state": "s", "nonce": "n", "code_challenge": ch, "username": "a"}
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(
        c.post("/oidc-stub/authorize", data=q, follow_redirects=False).headers["location"]).query)["code"][0]
    tok = {"grant_type": "authorization_code", "code": code, "client_id": "rmt-web", "redirect_uri": REDIRECT, "code_verifier": v}
    assert c.post("/oidc-stub/token", data=tok).status_code == 200
    assert c.post("/oidc-stub/token", data=tok).status_code == 400  # replayed code
    bad = {"response_type": "code", "code_challenge_method": "S256", **q, "redirect_uri": "https://evil.example/"}
    assert c.get("/oidc-stub/authorize", params=bad).status_code == 400


def test_stub_is_off_unless_dev(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISS)
    assert c.get("/oidc-stub/jwks").status_code == 404
    monkeypatch.setenv("OIDC_STUB", "1")
    assert c.get("/oidc-stub/jwks").status_code == 404  # RMT_ENV is not dev
    monkeypatch.setenv("RMT_ENV", "dev")
    assert c.get("/oidc-stub/jwks").status_code == 200


def test_outside_dev_signup_closes_and_http_issuer_is_refused(stub_on, monkeypatch):
    token = stub_login(c, "alice").json()["id_token"]
    monkeypatch.delenv("RMT_ENV")
    assert c.post("/users", json={"username": "x"}).status_code == 403  # OIDC configured: no anonymous API-key signup
    assert oidc.issuer() is None  # plain-http issuer outside dev: not trusted
    assert c.get("/users/me", headers=H(token)).status_code == 401
