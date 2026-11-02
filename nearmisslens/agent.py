from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    thoughts: list[dict] = field(default_factory=list)
    refusals: int = 0

    def decision_log(self) -> list[dict]:
        return [{"turn": s.turn, "tool": s.tool, "arguments": s.arguments, "result": s.result} for s in self.steps]

    def timeline(self) -> list[dict]:
        """Reasoning summaries and tool calls in order, with timings: the mission-control view of a run."""
        events = [{"turn": t["turn"], "kind": "thought", "text": t["text"]} for t in self.thoughts]
        events += [{"turn": s.turn, "kind": "tool", "tool": s.tool, "arguments": s.arguments,
                    "result": _public(s.result), "seconds": s.seconds} for s in self.steps]
        return sorted(events, key=lambda e: (e["turn"], e["kind"] != "thought"))


MEDIA_KEY = "_images"


def _public(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != MEDIA_KEY} if isinstance(result, dict) else result


def image_part(path: Path) -> dict:
    """An input_image part from a PNG or JPEG file, for tool results that show the model evidence."""
    path = Path(path)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"}


def tool_output(result: dict) -> str | list[dict]:
    """A function_call_output payload: JSON text, or text plus images when the result lists image files under
    MEDIA_KEY (the Responses API accepts input_text and input_image parts in tool results)."""
    text = json.dumps(_public(result), default=str)[:20000]
    images = result.get(MEDIA_KEY) if isinstance(result, dict) else None
    if not images:
        return text
    return [{"type": "input_text", "text": text}] + [image_part(p) for p in images]


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


def replay_items(response: dict) -> list[dict]:
    """A response's output as input items for the next turn: encrypted reasoning, function calls and assistant text,
    in their original order."""
    items = []
    for o in response.get("output", []):
        kind = o.get("type")
        if kind == "reasoning" and o.get("encrypted_content"):
            items.append({"type": "reasoning", "summary": o.get("summary") or [], "encrypted_content": o["encrypted_content"]})
        elif kind == "function_call":
            items.append({"type": "function_call", "call_id": o["call_id"], "name": o.get("name", ""),
                          "arguments": o.get("arguments") or "{}"})
        elif kind == "message":
            text = "".join(c.get("text", "") for c in o.get("content", []) or [] if c.get("type") == "output_text")
            items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
        elif kind in ("web_search_call", "tool_search_call", "tool_search_output"):  # server tools: replayed as given
            items.append({k: v for k, v in o.items() if k != "results"} if kind == "web_search_call" else o)
    return items


def run_agent(client: MetaClient, model: str, instructions: str, task: str, tools: list[Tool], max_turns: int,
              budget_usd: float, effort: str = "medium", tag: str = "agent", max_output_tokens: int = 8000,
              summaries: bool = False, escalate_after: int | None = None, required: tuple[str, ...] = (),
              governor: bool = False, max_nudges: int = 2, server_tools: list[dict] | None = None,
              include: tuple[str, ...] = (), on_response=None) -> AgentRun:
    """Function-calling loop on the Responses API with stateless replay: every turn resends the whole conversation,
    with the model's reasoning as encrypted reasoning items, and nothing is stored on the server. The cache key is the
    full request, so a run replays exactly and runs with different data never share a turn.
    A finish call whose result carries an error does not end the run; the model sees the error and can correct it.
    summaries asks for reasoning summaries (kept in run.thoughts). escalate_after stops the run with "escalated" after
    that many refused finish calls, so a person decides (Meta's verifiable-agent pattern).
    governor (adapter A1, for models that loop or stop early, measured in NML-Bench T22): a repeated identical call is
    not run again but answered "already done"; every tool result says which `required` tools are still missing; a
    reply with no tool call gets a nudge (up to max_nudges) instead of ending the run; and a client that forces a tool
    after N calls (open weights on Baseten) forces the next missing required tool rather than finish."""
    # tools named "namespace.function" are declared inside a namespace in server_tools (deferred, loaded by tool search)
    specs = [t.spec() for t in tools if "." not in t.name] + list(server_tools or [])
    by_name = {t.name: t for t in tools}
    run = AgentRun()
    conversation: list = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": task}]}]
    done: dict[str, object] = {}  # governor: tool+arguments already run -> its result
    nudges = 0
    called: set[str] = set()
    for turn in range(1, max_turns + 1):
        reasoning = {"effort": effort, **({"summary": "auto"} if summaries else {})}
        payload = {"model": model, "instructions": instructions, "tools": specs, "reasoning": reasoning,
                   "max_output_tokens": max_output_tokens, "store": False,
                   "include": ["reasoning.encrypted_content", *include], "input": list(conversation)}
        if governor and hasattr(client, "force_finish_after"):  # tells to_chat which tool to force when it forces one
            missing = [t for t in required if t not in called]
            payload["x_next_tool"] = missing[0] if missing else "finish"
        request = {k: v for k, v in payload.items() if k != "include"}

        def cost(resp):
            u = resp.get("usage") or {}
            cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
            # a client that serves the model itself (open weights on Baseten or Modal) prices its own tokens
            usd = client.usd(u) if hasattr(client, "usd") else \
                token_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0), cached)
            return usd, model, {
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
        if on_response is not None:
            on_response(resp)
        for o in resp.get("output", []):
            if o.get("type") == "reasoning":
                text = " ".join(x.get("text", "") for x in o.get("summary") or [] if isinstance(x, dict)).strip()
                if text:
                    run.thoughts.append({"turn": turn, "text": text})
        conversation += replay_items(resp)
        calls = _function_calls(resp)
        if not calls:
            run.final_text = _message_text(resp)
            if governor and nudges < max_nudges:
                nudges += 1
                missing = [t for t in required if t not in called]
                conversation.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                    "Continue with a tool call. " + (f"Still needed: {', '.join(missing)}." if missing else
                                                     "Every required tool has run: call finish with claims citing receipts.")}]})
                continue
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
            key = f"{name} {json.dumps(args, sort_keys=True)}"
            if governor and name != "finish" and key in done:
                result = {"note": "already done with these arguments; use the earlier result instead of calling again"}
            elif name not in by_name:
                result = {"error": f"unknown tool {name}"}
            else:
                try:
                    result = by_name[name].fn(**args)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
                if isinstance(result, dict) and "error" not in result:
                    done[key] = True
                    called.add(name)
            if governor and isinstance(result, dict) and name != "finish":
                missing = [x for x in required if x not in called]
                result = {**result, "next": (f"still needed: {', '.join(missing)}" if missing else
                                             "all required tools have run: call finish with claims citing receipts")}
            run.steps.append(Step(turn, name, args, result, round(time.time() - t, 2)))
            outputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": tool_output(result)})
            if name == "finish":
                if "error" not in result:
                    finished = True
                else:
                    run.refusals += 1
        conversation += outputs
        if finished:
            run.stopped = "finish_tool"
            break
        if escalate_after is not None and run.refusals >= escalate_after:
            run.stopped = "escalated"
            break
    else:
        run.stopped = "max_turns"
    return run

