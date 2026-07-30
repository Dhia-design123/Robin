"""
Shared Supabase client — used by both the local desktop app (friday/tools/reminders.py,
local_agent.py) and the cloud API (friday/cloud/*), so every surface reads/writes the
same reminders table instead of maintaining separate stores.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (.env locally, "
                "Vercel project env vars in production)."
            )
        _client = create_client(url, key)
    return _client
