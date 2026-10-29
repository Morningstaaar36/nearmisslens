from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from .cost import token_usd
from .meta_client import IncompleteResponse, MetaClient


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]

    def spec(self) -> dict:
        return {"type": "function", "name": self.name, "description": self.description,
                "parameters": self.parameters, "strict": True}


@dataclass
class Step:
    turn: int
    tool: str
    arguments: dict
    result: dict
    seconds: float


@dataclass
class AgentRun:
    steps: list[Step] = field(default_factory=list)
    final_text: str = ""
    usd: float = 0.0
    turns: int = 0
    stopped: str = ""

    def decision_log(self) -> list[dict]:
        return [{"turn": s.turn, "tool": s.tool, "arguments": s.arguments, "result": s.result} for s in self.steps]


def _function_calls(response: dict) -> list[dict]:
    return [o for o in response.get("output", []) if o.get("type") == "function_call"]


def _message_text(response: dict) -> str:
    parts = []
    for o in response.get("output", []):
        if o.get("type") == "message":
            for c in o.get("content", []) or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts)


def run_agent(client: MetaClient, model: str, instructions: str, task: str, tools: list[Tool], max_turns: int,
              budget_usd: float, effort: str = "medium", tag: str = "agent", max_output_tokens: int = 8000) -> AgentRun:
    """Function-calling loop on the Responses API. Instructions, tools and reasoning effort are re-sent every turn
    because previous_response_id does not carry them. Every model response is cached, so a run replays exactly.
    A finish call whose result carries an error does not end the run; the model sees the error and can correct it."""
    specs = [t.spec() for t in tools]
    by_name = {t.name: t for t in tools}
    run = AgentRun()
    previous_id: str | None = None
    next_input: list = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": task}]}]
    history: list = []
    for turn in range(1, max_turns + 1):
        payload = {"model": model, "instructions": instructions, "tools": specs, "reasoning": {"effort": effort},
                   "max_output_tokens": max_output_tokens, "input": next_input}
        if previous_id:
            payload["previous_response_id"] = previous_id
        history.append(next_input)
        request = {"model": model, "instructions": instructions, "tools": specs, "effort": effort, "history": history,
                   "max_output_tokens": max_output_tokens}

        def cost(resp):
            u = resp.get("usage") or {}
            cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
            return token_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0), cached), model, {
                "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

        remaining = budget_usd - run.usd
        if remaining <= 0:
            run.stopped = "budget"
            break
        try:
            resp = client.cached("agent", request, lambda: client.create_response(payload), cost,
                                 min(remaining, 0.5), f"{tag} turn {turn}")
        except IncompleteResponse as e:
            run.turns = turn
            run.stopped = f"incomplete: {e}"
            break
        run.usd += cost(resp)[0]
        run.turns = turn
        previous_id = resp.get("id")
        calls = _function_calls(resp)
        if not calls:
            run.final_text = _message_text(resp)
            run.stopped = "final_message"
            break
        outputs = []
        finished = False
        for call in calls:
            name = call.get("name", "")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t = time.time()
            if name not in by_name:
                result = {"error": f"unknown tool {name}"}
            else:
                try:
                    result = by_name[name].fn(**args)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
            run.steps.append(Step(turn, name, args, result, round(time.time() - t, 2)))
            outputs.append({"type": "function_call_output", "call_id": call["call_id"],
                            "output": json.dumps(result, default=str)[:20000]})
            if name == "finish" and "error" not in result:
                finished = True
        next_input = outputs
        if finished:
            run.stopped = "finish_tool"
            break
    else:
        run.stopped = "max_turns"
    return run

