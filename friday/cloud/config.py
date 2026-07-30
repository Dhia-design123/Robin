"""
Cloud-only configuration — env vars needed by the Vercel API that the local
desktop app doesn't use (Web Push, cron auth). Supabase/OpenAI env vars are
loaded directly where needed (friday/db/supabase_client.py, openai.OpenAI()),
same as the rest of the repo.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class CloudConfig:
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "")
    CRON_SECRET: str = os.getenv("CRON_SECRET", "")


cloud_config = CloudConfig()
