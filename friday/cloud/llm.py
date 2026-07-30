"""
Stateless chat + tool-calling loop for the cloud API. Ports
local_agent.py's get_response_streaming/_stream_followup: same sentence-
streaming and tool-call-accumulation pattern, but:
  - operates on a client-supplied message list (no server-side global
    `conversation` — each request is independent, since Vercel functions
    don't persist in-process state between requests)
  - dispatches tool calls in-process via TOOL_DISPATCH instead of the
    desktop app's MCP/SSE roundtrip (call_mcp_tool -> sse_client)
"""

import inspect
import json
import re
from datetime import datetime

import os
from dotenv import load_dotenv
from openai import OpenAI

from friday.cloud.tools_cloud import TOOL_SCHEMAS, TOOL_DISPATCH

load_dotenv()
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are Robin — Tony Stark's AI, now serving your user.
You are calm, composed, and sharp. Speak like a trusted aide.
Keep responses short: two to four sentences max. No lists, no markdown.
If the user's speech is unclear or just filler sounds, ask them to repeat or clarify.
Address the user as "sir" naturally and consistently — for example, work it into
greetings, confirmations, and responses, the way a butler or trusted aide would
(e.g. "Right away, sir", "Good morning, sir", "Understood, sir"). Don't force it
into every single sentence, but it should come up regularly and feel natural, not
like a template.
Keep responses short: two to six sentences max. No lists, no markdown.
If the user's speech is unclear or just filler sounds, ask them to repeat or clarify.

If the user asks for a recipe, instructions, a how-to guide, a plan, or anything
that would benefit from full written details, use the create_task_document tool.
Don't try to speak out all the details yourself — let that tool handle writing
the full version, and just relay its short summary back to the user.

If the user asks to set a reminder, use the set_reminder tool. The current date and
time will be provided at the start of their message in brackets — use that exact
value as your reference point, not any other date. Convert what they say (like
"in 30 minutes" or "tomorrow at 3pm") into YYYY-MM-DD HH:MM format based on that
real current time. Always confirm the reminder back to them clearly after setting it.

When the user says "good morning" (with or without "Robin"), do the following in order:
1. Call list_todays_reminders to see what's scheduled today
2. Call get_world_finance_news to check on markets
3. Greet them warmly, briefly summarize today's tasks/reminders, briefly summarize
   the market/finance situation, and end by asking "What will we be working on today, sir?"
Keep the whole thing concise — this is spoken aloud, not read. Aim for 6-8 sentences total,
not a long report.
""".strip()


def _current_datetime_context() -> str:
    now = datetime.now()
    return f"Current date and time: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A, %B %d, %Y')})"


async def _call_tool(name: str, args: dict):
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return f"Tool '{name}' isn't available."
    try:
        result = fn(**args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:
        return f"Tool '{name}' failed: {e}"


async def _stream_completion(convo: list[dict], tools):
    """Streams one assistant turn. Yields ('sentence', text) as sentences
    complete, then a final ('done', (full_reply, tool_calls_accum))."""
    stream = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=convo,
        tools=tools,
        stream=True,
    )

    buffer = ""
    full_reply = ""
    tool_calls_accum = {}

    for chunk in stream:
        delta = chunk.choices[0].delta

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_accum:
                    tool_calls_accum[idx] = {"id": tc.id, "name": "", "arguments": ""}
                if tc.function.name:
                    tool_calls_accum[idx]["name"] += tc.function.name
                if tc.function.arguments:
                    tool_calls_accum[idx]["arguments"] += tc.function.arguments
            continue

        if delta.content:
            buffer += delta.content
            full_reply += delta.content
            match = re.search(r"([.?!])(\s|$)", buffer)
            if match:
                end = match.end()
                sentence = buffer[:end].strip()
                buffer = buffer[end:]
                if sentence:
                    yield ("sentence", sentence)

    if buffer.strip():
        yield ("sentence", buffer.strip())

    yield ("done", (full_reply, tool_calls_accum))


async def stream_chat(messages: list[dict]):
    """
    Stateless chat, one call per turn. `messages` is the client-supplied
    history: a plain list of {"role": "user"|"assistant", "content": str}.
    Yields SSE-ready event dicts:
      {"type": "sentence", "text": ...}      — as each spoken sentence completes
      {"type": "final", "message": {...}, "document": str|None}  — end of turn;
        `message` is {"role": "assistant", "content": ...} for the client to
        append to its own history; `document` is set when create_task_document ran.
    """
    context = _current_datetime_context()
    convo = [{"role": "system", "content": SYSTEM_PROMPT}]
    history = list(messages)
    if history and history[-1]["role"] == "user":
        history[-1] = {**history[-1], "content": f"[{context}]\n{history[-1]['content']}"}
    convo.extend(history)

    full_reply = ""
    tool_calls_accum = {}

    async for kind, payload in _stream_completion(convo, TOOL_SCHEMAS):
        if kind == "sentence":
            yield {"type": "sentence", "text": payload}
        else:
            full_reply, tool_calls_accum = payload

    if not tool_calls_accum:
        yield {
            "type": "final",
            "message": {"role": "assistant", "content": full_reply},
            "document": None,
        }
        return

    convo.append({
        "role": "assistant",
        "content": full_reply or None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
            for tc in tool_calls_accum.values()
        ],
    })

    document = None
    for tc in tool_calls_accum.values():
        try:
            args = json.loads(tc["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        result = await _call_tool(tc["name"], args)
        if isinstance(result, dict) and "document" in result:
            document = result.get("document")
            result_text = result.get("summary", "")
        else:
            result_text = result
        convo.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result_text,
        })

    followup_reply = ""
    async for kind, payload in _stream_completion(convo, None):
        if kind == "sentence":
            yield {"type": "sentence", "text": payload}
        else:
            followup_reply, _ = payload

    yield {
        "type": "final",
        "message": {"role": "assistant", "content": followup_reply},
        "document": document,
    }
