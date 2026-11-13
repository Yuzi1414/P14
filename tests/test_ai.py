import asyncio
import json
import time

import httpx
import pytest

from reconcile.ai import AIError, AIWorker, LocalAI, load_config, status, validate_suggestion


def test_candidate_out_of_bounds_rejected():
    with pytest.raises(AIError, match="集合之外"):
        validate_suggestion("candidate", {"candidates":[{"id":"allowed"}]},
                            {"candidate_id":"invented", "reason":"same amount", "cleaning_notes":[]})


def test_candidate_explanation_cannot_override_computed_facts():
    suggestion=validate_suggestion("candidate", {"bank":{"name":"学生甲缴费","object_id":"S1","amount":"100.00"},
        "candidates":[{"id":"A","name":"学生甲","object_id":"S1","amount":"100.00"}]},
        {"candidate_id":"A","reason":"名称完全相同","cleaning_notes":[]})
    assert suggestion["verified_facts"]["name_exact"] is False
    assert suggestion["verified_facts"]["object_id_exact"] is True
    assert suggestion["verified_facts"]["date_exact"] is None


def test_mapping_unknown_column_and_duplicates_rejected():
    for mappings in ([{"field":"amount","column":"missing","reason":"x"}],
                     [{"field":"amount","column":"A","reason":"x"},{"field":"name","column":"A","reason":"x"}]):
        with pytest.raises(AIError):
            validate_suggestion("mapping", {"columns":["A"]}, {"mappings":mappings,"cleaning_notes":[]})


@pytest.mark.parametrize("mode", ["valid", "invalid_json", "timeout", "closed", "http_error", "malformed", "out_of_bounds"])
def test_local_transport_and_failure_modes(mode):
    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        body=json.loads(request.content)
        assert body["format"]["type"] == "object" and not body["stream"]
        if mode == "timeout": raise httpx.ReadTimeout("test", request=request)
        if mode == "closed": raise httpx.ConnectError("test", request=request)
        if mode == "http_error": return httpx.Response(404,json={"error":"not found"})
        if mode == "malformed": return httpx.Response(200,json={"nothing":True})
        content = "invalid" if mode == "invalid_json" else json.dumps({"candidate_id":"BAD" if mode == "out_of_bounds" else "A", "reason":"仅供复核","cleaning_notes":[]})
        return httpx.Response(200,json={"message":{"content":content}})
    client = LocalAI(transport=httpx.MockTransport(handler))
    if mode == "valid":
        assert asyncio.run(client.complete("candidate", {"candidates":[{"id":"A"}]}))["candidate_id"] == "A"
    else:
        with pytest.raises(AIError):
            asyncio.run(client.complete("candidate", {"candidates":[{"id":"A"}]}))


def test_default_backend_is_local_ollama(monkeypatch):
    for name in ("AI_PROVIDER", "AI_API_KEY", "DASHSCOPE_API_KEY", "AI_ENDPOINT", "AI_MODEL", "AI_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    config = load_config()
    assert config.local is True
    assert config.endpoint == "http://127.0.0.1:11434"
    assert config.model == "qwen3:4b"


def test_cloud_provider_uses_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "qwen")
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    monkeypatch.delenv("AI_ENDPOINT", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["model"] == "qwen-plus"
        assert body["stream"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content":
            "```json\n{\"candidate_id\":\"A\",\"reason\":\"同金额且有业务编号\",\"cleaning_notes\":[]}\n```"}}]})

    client = LocalAI(transport=httpx.MockTransport(handler))
    assert client.config.provider == "qwen"
    assert client.config.endpoint == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    result = asyncio.run(client.complete("candidate", {"candidates": [{"id": "A"}]}))
    assert result["candidate_id"] == "A"
    assert seen["url"].endswith("/compatible-mode/v1/chat/completions")
    assert seen["auth"] == "Bearer sk-test"


def test_cloud_without_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "dashscope")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    config = load_config()
    assert config.local is False
    assert config.configured is False
    assert LocalAI(config=config).health() is False
    info = status(config)
    assert info["ok"] is False and info["backend"] == "cloud"
    assert "AI_API_KEY" in info["hint"]
    with pytest.raises(AIError, match="AI_API_KEY"):
        AIWorker(LocalAI(config=config)).submit("candidate", {}, "task")


def test_disabled_ai_refuses_requests(monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "0")
    config = load_config()
    assert config.enabled is False and config.configured is False
    assert LocalAI(config=config).health() is False
    with pytest.raises(AIError, match="关闭"):
        asyncio.run(LocalAI(config=config).complete("candidate", {"candidates": [{"id": "A"}]}))


def test_worker_cancel_and_single_flight():
    class SlowClient:
        async def complete(self, kind, payload):
            await asyncio.sleep(30)
    worker=AIWorker(SlowClient())
    jid=worker.submit("candidate",{},"task")
    with pytest.raises(AIError):
        worker.submit("mapping",{},"task")
    worker.cancel(jid)
    for _ in range(100):
        if worker.jobs[jid].status != "running": break
        time.sleep(.01)
    assert worker.jobs[jid].status == "cancelled"

