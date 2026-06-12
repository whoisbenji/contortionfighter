"""
Shared agent runtime for all Contortion Space specialist agents.

One streaming/tool loop serves Luzia, Kooza, and Varekai. Each agent supplies
an AgentSpec (prompts + tool schemas + handlers); the host (dashboard server
or Alegría) supplies an AgentContext (event sink + one decision callback).

Human-in-the-loop decisions all flow through a single channel:
    ctx.decide(kind, payload) -> decision
The host decides how to collect the answer — the dashboard renders a panel
for `kind` and replies over the WebSocket; Alegría formats it as a chat
message and parses the user's reply (see decisions.py).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import anthropic

from .config import MODEL, MAX_TOKENS


class DecisionAborted(Exception):
    """Raised when a blocking decision can never be answered (e.g. client disconnected)."""


class AgentContext:
    """Host-supplied callbacks for one agent run."""

    def __init__(
        self,
        on_event: Callable[[dict], None],
        check_pause: Callable[[], str | None] | None = None,
        decide: Callable[[str, dict], Any] | None = None,
    ):
        self.on_event = on_event or (lambda e: None)
        self.check_pause = check_pause or (lambda: None)
        self._decide = decide or _default_decide

    def decide(self, kind: str, payload: dict) -> Any:
        decision = self._decide(kind, payload)
        if decision is None:
            raise DecisionAborted(f"No decision received for '{kind}' — client disconnected?")
        return decision


def _default_decide(kind: str, payload: dict) -> Any:
    """Headless defaults — conservative: skip/decline everything."""
    from .decisions import default_decision
    return default_decision(kind, payload)


class AgentSpec:
    """Declarative description of one agent.

    blocking_tools: tool_name -> handler(tool_input, ctx) -> JSON-serialisable result.
        The handler typically calls ctx.decide(...) and returns the decision
        as the tool result. The runtime never dispatches these to tool_functions.
    pre_tool: called before normal dispatch — side effects only (e.g. photo check).
    after_tool: called after normal dispatch with the result. May return a
        modified result to send to the model (e.g. trimming a huge audit list);
        return None to use the result unchanged.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict],
        tool_functions: dict[str, Callable],
        tool_phase_map: dict[str, tuple[int, str]] | None = None,
        blocking_tools: dict[str, Callable[[dict, AgentContext], Any]] | None = None,
        pre_tool: Callable[[str, dict, AgentContext], None] | None = None,
        after_tool: Callable[[str, dict, dict, AgentContext], dict | None] | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_functions = tool_functions
        self.tool_phase_map = tool_phase_map or {}
        self.blocking_tools = blocking_tools or {}
        self.pre_tool = pre_tool
        self.after_tool = after_tool

    def dispatch(self, tool_name: str, tool_input: dict) -> Any:
        fn = self.tool_functions.get(tool_name)
        if fn is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return fn(**tool_input)
        except Exception as exc:
            return {"error": str(exc)}


def _stream_response(client, on_event, **kwargs):
    """Stream a response, emitting thinking_delta events for text tokens.

    Returns the final Message object. Retries with backoff on rate limits.
    """
    delays = [10, 30, 60, 120]
    for delay in delays + [None]:
        try:
            thinking_id = f"thinking-{int(time.time() * 1000)}"
            text_buf = []
            with client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and hasattr(event, "delta")
                        and getattr(event.delta, "type", "") == "text_delta"
                    ):
                        chunk = event.delta.text
                        if chunk:
                            text_buf.append(chunk)
                            on_event({"type": "thinking_delta", "id": thinking_id, "text": chunk})
            if text_buf:
                on_event({"type": "thinking_done", "id": thinking_id})
            return stream.get_final_message()
        except anthropic.RateLimitError:
            if delay is None:
                raise
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code == 429 and delay is not None:
                time.sleep(delay)
            else:
                raise


def _truncate_input(tool_input: dict) -> dict:
    return {
        k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
        for k, v in tool_input.items()
    }


def run_loop(
    spec: AgentSpec,
    messages: list[dict],
    ctx: AgentContext,
    tools_override: list[dict] | None = None,
    verbose: bool = False,
) -> str:
    """The one true agent loop: stream → dispatch tools → repeat until end_turn."""
    import os

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    active_tools = tools_override if tools_override is not None else spec.tools
    current_phase = 0
    on_event = ctx.on_event

    while True:
        on_event({"type": "thinking"})

        response = _stream_response(
            client,
            on_event,
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=spec.system_prompt,
            tools=active_tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = "".join(b.text for b in response.content if hasattr(b, "text"))
            on_event({"type": "summary", "text": final_text})
            if verbose:
                print(f"\n✅ {spec.name} complete.\n{final_text}")
            return final_text

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        interjection: str | None = None

        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input or {}

            phase_num, phase_label = spec.tool_phase_map.get(tool_name, (current_phase, "Working"))
            if phase_num != current_phase:
                current_phase = phase_num
                on_event({"type": "phase", "phase": phase_num, "label": phase_label})

            on_event({"type": "tool_call", "tool": tool_name, "input": _truncate_input(tool_input)})
            if verbose:
                print(f"\n🔧 {tool_name}: {json.dumps(tool_input)[:200]}")

            # ── Blocking tools: route through the decision channel ────────
            if tool_name in spec.blocking_tools:
                result = spec.blocking_tools[tool_name](tool_input, ctx)
                result_str = json.dumps(result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })
                on_event({"type": "tool_result", "tool": tool_name,
                          "result": result_str[:500], "ok": True})
                continue

            # ── Pre-dispatch hook (e.g. Luzia's photo check) ──────────────
            if spec.pre_tool:
                spec.pre_tool(tool_name, tool_input, ctx)

            # ── Collect any interjection; applied after this tool batch ──
            if interjection is None:
                interjection = ctx.check_pause()

            result = spec.dispatch(tool_name, tool_input)

            result_for_model = None
            if spec.after_tool:
                result_for_model = spec.after_tool(tool_name, tool_input, result, ctx)
            if result_for_model is None:
                result_for_model = result

            result_preview = json.dumps(result, ensure_ascii=False)
            on_event({
                "type": "tool_result",
                "tool": tool_name,
                "result": result_preview[:500] + ("…" if len(result_preview) > 500 else ""),
                "ok": not (isinstance(result, dict) and "error" in result),
            })
            if verbose:
                print(f"   → {result_preview[:300]}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result_for_model),
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        # Interjections are appended after tool_results so the message
        # sequence stays valid (tool_use must be answered by tool_result).
        if interjection:
            messages.append({"role": "user", "content": (
                f"[User interjection]: {interjection}\n"
                "Please take this into account and adjust your next action accordingly."
            )})

    return "Agent loop ended unexpectedly."
