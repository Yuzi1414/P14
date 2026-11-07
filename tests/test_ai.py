import asyncio
import json
import time

import httpx
import pytest

from reconcile.ai import AIError, AIWorker, LocalAI, validate_suggestion


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

