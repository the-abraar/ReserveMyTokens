"""No network: requests is mocked in both modules."""
from unittest import mock

from reserve_my_tokens_worker import polling_client
from reserve_my_tokens_worker.ollama_adapter import OllamaAdapter
from reserve_my_tokens_worker.polling_client import CoordinatorClient


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
