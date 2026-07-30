from datetime import datetime

from friday.db import reminders as db


def register(mcp):
    @mcp.tool()
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

        db.create_reminder(text, due)
        return f"Reminder set: '{text}' at {due.strftime('%I:%M %p on %B %d')}."

    @mcp.tool()
    def list_reminders() -> str:
        """Lists all upcoming (not yet done) reminders."""
        upcoming = db.list_reminders()
        if not upcoming:
            return "You have no upcoming reminders."
        lines = [f"- {r['text']} at {r['due']}" for r in upcoming]
        return "\n".join(lines)

    @mcp.tool()
    def delete_reminder(reminder_id: int) -> str:
        """Deletes/cancels a reminder by its ID number."""
        db.delete_reminder(reminder_id)
        return f"Reminder {reminder_id} deleted."

    @mcp.tool()
    def list_todays_reminders() -> str:
        """Lists only the reminders due today (not future days)."""
        todays = db.list_todays_reminders()
        if not todays:
            return "No reminders or tasks scheduled for today."
        lines = [f"- {r['text']} at {datetime.strptime(r['due'], '%Y-%m-%d %H:%M').strftime('%I:%M %p')}" for r in todays]
        return "\n".join(lines)