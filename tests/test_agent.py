import json

from nearmisslens.agent import Tool, run_agent


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def cached(self, namespace, request, run, cost_fn, estimate, what, require_text=False):
        return run()

    def create_response(self, payload):
        self.payloads.append(payload)
        return self.responses.pop(0)


def call(name, args, cid):
    return {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": cid}


def usage():
    return {"input_tokens": 1000, "output_tokens": 100}


def test_agent_loop_runs_tools_and_stops_on_finish():
    seen = []
    tools = [Tool("add", "add", {"type": "object", "properties": {"a": {"type": "number"}}, "required": ["a"],
                                  "additionalProperties": False}, lambda a: seen.append(a) or {"sum": a + 1}),
             Tool("finish", "stop", {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                  lambda: {"ok": True})]
    fc = FakeClient([{"id": "r1", "output": [call("add", {"a": 2}, "c1")], "usage": usage()},
                     {"id": "r2", "output": [call("finish", {}, "c2")], "usage": usage()}])
    run = run_agent(fc, "muse-spark-1.3", "be brief", "task", tools, max_turns=5, budget_usd=1.0)
    assert seen == [2] and run.stopped == "finish_tool" and run.turns == 2
    assert fc.payloads[1]["previous_response_id"] == "r1"
    assert fc.payloads[1]["tools"] and fc.payloads[1]["instructions"] == "be brief"
    assert fc.payloads[1]["input"][0]["type"] == "function_call_output"
    assert run.decision_log()[0]["result"] == {"sum": 3}


def test_agent_reports_tool_errors_and_final_message():
    tools = [Tool("boom", "fails", {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                  lambda: 1 / 0)]
    fc = FakeClient([{"id": "r1", "output": [call("boom", {}, "c1")], "usage": usage()},
                     {"id": "r2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}],
                      "usage": usage()}])
    run = run_agent(fc, "muse-spark-1.3", "x", "task", tools, max_turns=5, budget_usd=1.0)
    assert "ZeroDivisionError" in run.steps[0].result["error"] and run.final_text == "done"
