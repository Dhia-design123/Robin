"""
Web Push sending — used by the /api/cron/due-reminders endpoint to notify
subscribed devices (phones/browsers) when a reminder comes due.
"""

import json

from pywebpush import webpush, WebPushException

from friday.cloud.config import cloud_config
from friday.cloud import db_push


def send_web_push(subscription_row: dict, title: str, body: str) -> bool:
    """Sends one push notification. Returns False (and removes the stale
    subscription) if the endpoint is no longer valid."""
    subscription_info = {
        "endpoint": subscription_row["endpoint"],
        "keys": {
            "p256dh": subscription_row["p256dh"],
            "auth": subscription_row["auth"],
        },
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=cloud_config.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": cloud_config.VAPID_SUBJECT},
        )
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            db_push.delete_subscription(subscription_row["id"])
        return False


def notify_all_devices(title: str, body: str) -> int:
    """Sends the same notification to every subscribed device. Returns the
    number of successful deliveries."""
    sent = 0
    for row in db_push.get_all_subscriptions():
        if send_web_push(row, title, body):
            sent += 1
    return sent
