"""No network: requests is mocked in both modules."""
import ast
import base64
import pathlib
from unittest import mock

import keyring
import pytest
from click.testing import CliRunner
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from reserve_my_tokens_worker import cli, credentials, polling_client, receipts
from reserve_my_tokens_worker.limits import Limits
from reserve_my_tokens_worker.ollama_adapter import OllamaAdapter
from reserve_my_tokens_worker.polling_client import CoordinatorClient, parse_job
from reserve_my_tokens_worker.provider import RESULT_KEYS, ModelProvider


def resp(status=200, body=None):
    r = mock.Mock(status_code=status)
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


def test_adapter_passes_temperature_and_maps_metrics():
    with mock.patch("reserve_my_tokens_worker.ollama_adapter.requests.post",
                    return_value=resp(body={"response": "hi", "prompt_eval_count": 2, "eval_count": 3, "eval_duration": 4})) as p:
        out = OllamaAdapter("http://o").run_inference("m", "p", 50, 0.7)
    assert p.call_args.args[0] == "http://o/api/generate"
    assert p.call_args.kwargs["json"]["options"] == {"num_predict": 50, "temperature": 0.7}
    assert out == {"output": "hi", "prompt_tokens": 2, "completion_tokens": 3, "eval_duration_ns": 4}


def test_adapter_detect_models():
    with mock.patch("reserve_my_tokens_worker.ollama_adapter.requests.get", return_value=resp(body={"models": [{"name": "a"}]})):
        assert OllamaAdapter().detect_models() == ["a"]


def test_client_lease_204_and_job():
    with mock.patch.object(polling_client.requests, "Session") as S:
        s = S.return_value
        s.headers = {}
        cl = CoordinatorClient("http://c/", 7, "tok")
        s.post.return_value = resp(204)
        assert cl.lease(["m"]) is None
        s.post.return_value = resp(200, {"job_id": 1})
        assert cl.lease(["m"]) == {"job_id": 1}
        assert s.post.call_args.args[0] == "http://c/workers/7/lease"
        assert s.headers["Authorization"] == "Bearer tok"


def test_polling_passes_job_temperature_to_ollama():
    with mock.patch.object(polling_client.requests, "Session") as S:
        s = S.return_value
        s.headers = {}
        cl = CoordinatorClient("http://c", 7, "tok", poll_interval=0)
        job = {"job_id": 1, "model": "m", "prompt": "p", "max_tokens": 9, "temperature": 0.5}
        res = {"output": "o", "prompt_tokens": 1, "completion_tokens": 2, "eval_duration_ns": 3}
        s.post.side_effect = [resp(200, job), resp(200, {"settled": True}), KeyboardInterrupt()]
        ollama = mock.Mock()
        ollama.run_inference.return_value = res
        cl.start_polling(ollama, ["m"])  # KeyboardInterrupt on 3rd call ends the loop cleanly
    ollama.run_inference.assert_called_once_with("m", "p", 9, 0.5)
    assert s.post.call_args_list[1].args[0] == "http://c/jobs/1/result"
    assert s.post.call_args_list[1].kwargs["json"] == res


# ---- adapter contract, keychain, receipts, limits, Boundary A and D ------------------------------------------------

PKG = pathlib.Path(cli.__file__).parent


class MemKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        if (s, u) not in self.d:
            raise keyring.errors.PasswordDeleteError(u)
        del self.d[(s, u)]


@pytest.fixture
def mem_keyring():
    old, kr = keyring.get_keyring(), MemKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(old)


def test_ollama_adapter_implements_the_provider_contract():
    assert issubclass(OllamaAdapter, ModelProvider)
    with mock.patch("reserve_my_tokens_worker.ollama_adapter.requests.post",
                    return_value=resp(body={"response": "hi", "eval_count": 1})):
        assert set(OllamaAdapter().run_inference("m", "p", 5)) == RESULT_KEYS

    class Half(ModelProvider):
        def detect_models(self):
            return []
    with pytest.raises(TypeError):
        Half()


def test_keychain_roundtrip(mem_keyring):
    credentials.save("http://c/", 3, "tok", "key")
    assert credentials.load("http://c", 3) == {"token": "tok", "signing_key": "key"}
    assert credentials.delete("http://c", 3) and credentials.load("http://c", 3) is None
    assert credentials.delete("http://c", 3) is False


def test_signature_verifies_with_the_public_key():
    k = receipts.new_key()
    res = {"output": "o", "prompt_tokens": 1, "completion_tokens": 2, "eval_duration_ns": 3}
    sig = base64.b64decode(receipts.sign(k, 9, 4, res))
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(receipts.public_key(k)))
    pub.verify(sig, receipts.payload(9, 4, "o", 1, 2, 3))  # raises on mismatch
    with pytest.raises(InvalidSignature):
        pub.verify(sig, receipts.payload(9, 4, "o", 1, 99, 3))  # inflated tokens break the signature


def test_limits_window_and_kill_switch(tmp_path):
    lim = Limits(max_compute_seconds=10, max_tokens=100, kill_file=tmp_path / "STOP")
    assert lim.remaining_tokens(1000) == 100 and not lim.exhausted(1000)
    lim.record(4, 60, now=1000)
    assert lim.remaining_tokens(1000) == 40
    lim.record(7, 10, now=1001)
    assert lim.exhausted(1002)  # 11 s of compute > 10
    assert not lim.exhausted(1000 + 86400 + 2)  # both entries left the 24 h window
    assert not lim.killed()
    (tmp_path / "STOP").touch()
    assert lim.killed()


def test_lease_sends_long_poll_wait_and_token_budget():
    with mock.patch.object(polling_client.requests, "Session") as S:
        s = S.return_value
        s.headers = {}
        cl = CoordinatorClient("http://c", 7, "tok", wait=15)
        s.post.return_value = resp(204)
        assert cl.lease(["m"], max_tokens=9000) is None
    assert s.post.call_args.kwargs["params"] == {"wait": 15}
    assert s.post.call_args.kwargs["json"] == {"models": ["m"], "max_tokens": 4096}
    assert s.post.call_args.kwargs["timeout"] > 15


def test_exhausted_limits_do_not_lease(tmp_path):
    with mock.patch.object(polling_client.requests, "Session") as S, mock.patch.object(polling_client.time, "sleep"):
        S.return_value.headers = {}
        cl = CoordinatorClient("http://c", 7, "tok", limits=Limits(max_tokens=5))
        cl.limits.record(1, 5)
        assert cl._serve_one(mock.Mock(), ["m"]) is False
    S.return_value.post.assert_not_called()


# Boundary D: inference only.
@pytest.mark.parametrize("job", [
    {"job_id": 1, "model": "m", "prompt": "p", "max_tokens": 5, "command": "rm -rf ~"},
    {"job_id": 1, "model": "m", "prompt": "p", "max_tokens": 5, "type": "shell"},
    {"job_id": 1, "model": "other", "prompt": "p", "max_tokens": 5},
    {"job_id": 1, "model": "m", "prompt": ["p"], "max_tokens": 5},
    {"job_id": 1, "model": "m", "prompt": "p", "max_tokens": True},
    {"job_id": 1, "model": "m", "prompt": "p", "max_tokens": 99999},
    {"job_id": 1, "model": "m", "prompt": "p"},
])
def test_worker_refuses_anything_but_an_offered_inference_job(job):
    with pytest.raises(ValueError):
        parse_job(job, ["m"])
    with mock.patch.object(polling_client.requests, "Session") as S:
        s = S.return_value
        s.headers = {}
        s.post.side_effect = [resp(200, job), KeyboardInterrupt()]
        provider = mock.Mock()
        CoordinatorClient("http://c", 7, "tok", poll_interval=0).start_polling(provider, ["m"])
    provider.run_inference.assert_not_called()
    assert s.post.call_count == 2  # the lease, then the next lease: no result was submitted


def test_worker_package_has_no_exec_paths():
    banned_mods = {"subprocess", "pty", "pickle", "marshal", "shutil", "ctypes", "multiprocessing"}
    banned_calls = {"eval", "exec", "compile", "__import__", "system", "popen", "spawnv", "execv", "execvp", "startfile"}
    for f in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import | ast.ImportFrom):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not {m.split(".")[0] for m in mods} & banned_mods, (f.name, mods)
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                assert name not in banned_calls, (f.name, name)


# Boundary A: nothing but the worker token and the result leaves the machine; no keys, no host secrets.
def test_no_local_secrets_reach_the_coordinator(mem_keyring, monkeypatch, tmp_path):
    secrets = {"OPENAI_API_KEY": "sk-host-secret-1", "ANTHROPIC_API_KEY": "sk-ant-host-secret-2"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    sent = []

    def record(method):
        def f(url, **kw):
            sent.append((method, url, dict(S.return_value.headers), kw))
            if url.endswith("/lease"):
                if sum(1 for m, u, *_ in sent if u.endswith("/lease")) > 1:
                    (tmp_path / "STOP").touch()  # kill switch ends the run
                    return resp(204)
                return resp(200, {"job_id": 5, "model": "m", "prompt": "p", "max_tokens": 9, "temperature": 0})
            return resp(200, {"ok": True})
        return f
    with mock.patch.object(polling_client.requests, "Session") as S, \
            mock.patch.object(cli, "OllamaAdapter") as O:
        S.return_value.headers = {}
        S.return_value.post.side_effect = record("POST")
        S.return_value.put.side_effect = record("PUT")
        O.return_value.detect_models.return_value = ["m"]
        O.return_value.run_inference.return_value = {"output": "o", "prompt_tokens": 1, "completion_tokens": 2,
                                                     "eval_duration_ns": 3}
        r = CliRunner().invoke(cli.main, ["login", "--worker-id", "5", "--coordinator-url", "http://c"], input="wtok\n")
        assert r.exit_code == 0, r.output
        r = CliRunner().invoke(cli.main, ["start", "--worker-id", "5", "--coordinator-url", "http://c", "--wait", "0",
                                          "--poll-interval", "0", "--kill-file", str(tmp_path / "STOP")])
        assert r.exit_code == 0, r.output
    private_key = credentials.load("http://c", 5)["signing_key"]
    assert [(m, u.rsplit("/", 1)[1]) for m, u, *_ in sent] == [("PUT", "public_key"), ("POST", "lease"), ("POST", "result"),
                                                            ("POST", "lease")]
    for _, _, headers, kw in sent:
        assert headers == {"Authorization": "Bearer wtok"}
        blob = repr(kw)
        assert private_key not in blob and not any(v in blob for v in secrets.values())
    assert set(sent[2][3]["json"]) == RESULT_KEYS | {"signature"}
    assert set(sent[0][3]["json"]) == {"public_key"}


def test_stop_command_sets_the_kill_switch(tmp_path):
    r = CliRunner().invoke(cli.main, ["stop", "--kill-file", str(tmp_path / "d" / "STOP")])
    assert r.exit_code == 0 and (tmp_path / "d" / "STOP").exists()
