"""
Cloud tool set — plain functions (no MCP decorators), called in-process by
friday/cloud/llm.py's chat loop. No SSE/MCP roundtrip: this is a fixed, small
tool set so a static schema list is simpler and faster than the dynamic
MCP tool discovery local_agent.py does against server.py.

Reuses portable logic from friday/tools/ where the underlying helpers are
plain module-level functions (friday/tools/web.py's feed-fetching), and
reimplements the reminder/task-doc tools against the shared friday/db store
(friday/tools/reminders.py's tool bodies are nested inside register(mcp) and
so aren't directly importable — this mirrors their logic instead).

Deliberately excluded (see plan): friday/tools/system_control.py's tools
(open_application, run_shell_command, workspace_launch, list_directory) and
web.py's open_world_monitor/open_finance_world_monitor — all act on "the
machine this process runs on", which on Vercel is not the user's machine.
"""

import asyncio
import os
import platform
from datetime import datetime

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from friday.tools.web import fetch_and_parse_feed, SEED_FEEDS, FINANCE_SEED_FEEDS
from friday.db import reminders as reminders_db

load_dotenv()
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def get_world_news() -> str:
    """Fetches the latest global headlines from major news outlets simultaneously."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        results_of_lists = await asyncio.gather(
            *(fetch_and_parse_feed(client, url) for url in SEED_FEEDS)
        )
        all_articles = [item for sublist in results_of_lists for item in sublist]

    if not all_articles:
        return "The global news grid is unresponsive, sir. I'm unable to pull headlines."

    report = ["### GLOBAL NEWS BRIEFING (LIVE)\n"]
    for entry in all_articles[:12]:
        report.append(f"**[{entry['source']}]** {entry['title']}")
        report.append(f"{entry['summary']}")
        report.append(f"Link: {entry['link']}\n")
    return "\n".join(report)


async def get_world_finance_news() -> str:
    """Fetches the latest finance and market headlines from major financial outlets simultaneously."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        results_of_lists = await asyncio.gather(
            *(fetch_and_parse_feed(client, url) for url in FINANCE_SEED_FEEDS)
        )
        all_articles = [item for sublist in results_of_lists for item in sublist]

    if not all_articles:
        return "The financial feeds are unresponsive right now, sir. I can't pull market headlines."

    report = ["### FINANCE BRIEFING (LIVE)\n"]
    for entry in all_articles[:12]:
        report.append(f"**[{entry['source']}]** {entry['title']}")
        report.append(f"{entry['summary']}")
        report.append(f"Link: {entry['link']}\n")
    return "\n".join(report)


async def search_web(query: str) -> str:
    """Search the web for a given query and return a summary of results."""
    return f"[stub] Search results for: {query}"


async def fetch_url(url: str) -> str:
    """Fetch the raw text content of a URL."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text[:4000]


def get_current_time() -> str:
    """Return the current date and time in ISO 8601 format."""
    return datetime.now().isoformat()


def get_system_info() -> dict:
    """Return basic host info. NOTE: on the cloud API this describes the
    serverless container the request happened to run on, not the user's PC."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }


def set_reminder(text: str, due_datetime: str) -> str:
    """
    Creates a reminder. due_datetime must be in ISO format: YYYY-MM-DD HH:MM (24-hour).

    Interpret vague time phrases using these defaults:
    - "morning" / "tomorrow morning" -> 9:00 AM the next day
    - "afternoon" -> 2:00 PM
    - "evening" / "tonight" -> 7:00 PM
    - "remind me" with NO time specified at all -> default to 9:00 AM tomorrow
    - Relative times ("in 30 minutes", "in an hour") -> calculate from current time
    - If they say a specific time ("at 5pm", "at 3:30"), use that exactly
    """
    try:
        due = datetime.strptime(due_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        return "I couldn't understand that date/time format. Please try again."

    reminders_db.create_reminder(text, due)
    return f"Reminder set: '{text}' at {due.strftime('%I:%M %p on %B %d')}."


def list_reminders() -> str:
    """Lists all upcoming (not yet done) reminders."""
    upcoming = reminders_db.list_reminders()
    if not upcoming:
        return "You have no upcoming reminders."
    return "\n".join(f"- {r['text']} at {r['due']}" for r in upcoming)


def delete_reminder(reminder_id: int) -> str:
    """Deletes/cancels a reminder by its ID number."""
    reminders_db.delete_reminder(reminder_id)
    return f"Reminder {reminder_id} deleted."


def list_todays_reminders() -> str:
    """Lists only the reminders due today (not future days)."""
    todays = reminders_db.list_todays_reminders()
    if not todays:
        return "No reminders or tasks scheduled for today."
    return "\n".join(
        f"- {r['text']} at {datetime.strptime(r['due'], '%Y-%m-%d %H:%M').strftime('%I:%M %p')}"
        for r in todays
    )


def create_task_document(topic: str, task_type: str = "general") -> dict:
    """
    Researches a topic (recipe, how-to, instructions, plan, etc.) and writes
    full detailed content for it. Returns a short 1-2 sentence summary to be
    spoken aloud, plus the full document text for the client to display.

    task_type examples: 'recipe', 'how-to', 'plan', 'general'
    """
    try:
        prompt = f"""Write complete, detailed {task_type} content for: {topic}

Include all necessary steps, ingredients, or details a person would need to
actually follow this without needing anything else. Format it clearly with
headers and numbered/bulleted steps where appropriate. Be thorough."""

        completion = _client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
        full_content = completion.choices[0].message.content

        summary_prompt = f"""Summarize this in exactly 1-2 short spoken sentences,
as if telling someone what you just wrote down for them:

{full_content}"""
        summary_completion = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = summary_completion.choices[0].message.content

        return {
            "summary": f"{summary} I've written up the full details for you.",
            "document": full_content,
        }
    except Exception as e:
        return {"summary": f"I ran into an issue creating that document: {e}", "document": None}


TOOL_DISPATCH = {
    "get_world_news": get_world_news,
    "get_world_finance_news": get_world_finance_news,
    "search_web": search_web,
    "fetch_url": fetch_url,
    "get_current_time": get_current_time,
    "get_system_info": get_system_info,
    "set_reminder": set_reminder,
    "list_reminders": list_reminders,
    "delete_reminder": delete_reminder,
    "list_todays_reminders": list_todays_reminders,
    "create_task_document": create_task_document,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_world_news",
            "description": "Fetches the latest global headlines from major news outlets simultaneously. Use this when the user asks 'What's going on in the world?' or for recent events.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_finance_news",
            "description": "Fetches the latest finance and market headlines from major financial outlets simultaneously. Use this when the user asks about finance news, market updates, or economic developments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for a given query and return a summary of results.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the raw text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Return the current date and time in ISO 8601 format.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Return basic information about the host system.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Creates a reminder. due_datetime must be in ISO format: YYYY-MM-DD HH:MM (24-hour). "
                "Interpret vague time phrases using these defaults: 'morning'/'tomorrow morning' -> "
                "9:00 AM the next day; 'afternoon' -> 2:00 PM; 'evening'/'tonight' -> 7:00 PM; "
                "'remind me' with no time specified -> default to 9:00 AM tomorrow; relative times "
                "('in 30 minutes', 'in an hour') -> calculate from current time; a specific time "
                "('at 5pm', 'at 3:30') -> use that exactly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "due_datetime": {"type": "string"},
                },
                "required": ["text", "due_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Lists all upcoming (not yet done) reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Deletes/cancels a reminder by its ID number.",
            "parameters": {
                "type": "object",
                "properties": {"reminder_id": {"type": "integer"}},
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todays_reminders",
            "description": "Lists only the reminders due today (not future days).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task_document",
            "description": (
                "Researches a topic (recipe, how-to, instructions, plan, etc.), writes full "
                "detailed content for it, and returns a short spoken summary plus the full "
                "document text. Use this when the user asks for a recipe, instructions, a "
                "how-to guide, a plan, or anything that would benefit from full written details "
                "— don't try to speak out all the details yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "task_type": {"type": "string", "description": "e.g. 'recipe', 'how-to', 'plan', 'general'"},
                },
                "required": ["topic"],
            },
        },
    },
]
