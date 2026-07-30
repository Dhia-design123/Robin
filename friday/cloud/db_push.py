"""
Push-subscription storage (Supabase-backed). Unlike reminders, this IS scoped
per device — each browser/PWA instance has its own push endpoint to notify.
"""

from friday.db.supabase_client import get_client

TABLE = "push_subscriptions"


def upsert_subscription(device_id: str, subscription: dict) -> dict:
    row = {
        "device_id": device_id,
        "endpoint": subscription["endpoint"],
        "p256dh": subscription["keys"]["p256dh"],
        "auth": subscription["keys"]["auth"],
    }
    result = (
        get_client()
        .table(TABLE)
        .upsert(row, on_conflict="device_id,endpoint")
        .execute()
    )
    return result.data[0]


def get_all_subscriptions() -> list[dict]:
    result = get_client().table(TABLE).select("*").execute()
    return result.data


def delete_subscription(subscription_id: int) -> None:
    get_client().table(TABLE).delete().eq("id", subscription_id).execute()
