"""
Shared reminders store (Supabase-backed). Single source of truth for reminders —
used by friday/tools/reminders.py (desktop MCP tools + local_agent.py's background
check) and friday/cloud/tools_cloud.py (cloud chat API) alike, so a reminder set on
any device shows up on all of them.
"""

from datetime import datetime

from friday.db.supabase_client import get_client

TABLE = "reminders"
DUE_FORMAT = "%Y-%m-%d %H:%M"


def create_reminder(text: str, due: datetime) -> dict:
    row = {
        "text": text,
        "due": due.strftime(DUE_FORMAT),
        "done": False,
    }
    result = get_client().table(TABLE).insert(row).execute()
    return result.data[0]


def list_reminders() -> list[dict]:
    result = (
        get_client()
        .table(TABLE)
        .select("*")
        .eq("done", False)
        .order("due")
        .execute()
    )
    return result.data


def delete_reminder(reminder_id: int) -> bool:
    result = get_client().table(TABLE).delete().eq("id", reminder_id).execute()
    return len(result.data) > 0


def list_todays_reminders() -> list[dict]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    reminders = list_reminders()
    return [r for r in reminders if r["due"].startswith(today_str)]


def list_all_due(now: datetime) -> list[dict]:
    """Not-yet-done reminders whose due time has passed. Used by the desktop
    background loop and the cloud cron endpoint alike."""
    reminders = list_reminders()
    now_str = now.strftime(DUE_FORMAT)
    return [r for r in reminders if r["due"] <= now_str]


def mark_done(reminder_id: int) -> None:
    get_client().table(TABLE).update({"done": True}).eq("id", reminder_id).execute()
