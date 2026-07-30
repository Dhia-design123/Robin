"""
Robin HUD (web-based) — full overlay window using pywebview.
"""

import webview
import threading
import time
import os
import json
from datetime import datetime

hud_window = None
_current_state = {
    "speaking": False,
    "muted": False,
    "time": "",
    "date": "",
    "status": "Active",
    "reminders": "No reminders"
}


def _clock_updater():
    while True:
        now = datetime.now()
        _current_state["time"] = now.strftime("%I:%M %p")
        _current_state["date"] = now.strftime("%A, %B %d")
        push_update()
        time.sleep(1)


def push_update():
    if hud_window:
        try:
            js = f"updateHUD({json.dumps(_current_state)})"
            hud_window.evaluate_js(js)
        except Exception:
            pass


def set_speaking(is_speaking: bool):
    _current_state["speaking"] = is_speaking
    _current_state["status"] = "Speaking" if is_speaking else "Active"
    push_update()


def set_muted(is_muted: bool):
    _current_state["muted"] = is_muted
    _current_state["status"] = "Muted" if is_muted else "Active"
    push_update()


def set_reminders_text(text: str):
    _current_state["reminders"] = text
    push_update()


def create_window():
    """Creates the webview window object. Call this before start_blocking()."""
    global hud_window
    html_path = os.path.join(os.path.dirname(__file__), "hud_display.html")
    hud_window = webview.create_window(
        "Robin",
        html_path,
        transparent=True,
        frameless=True,
        on_top=True,
        width=1920,   # <-- update to your resolution
        height=1080,  # <-- update to your resolution
        x=0, y=0,
        resizable=False,
    )
    return hud_window


def start_blocking():
    """Starts the webview event loop. MUST be called on the main thread — blocks forever."""
    clock_thread = threading.Thread(target=_clock_updater, daemon=True)
    clock_thread.start()
    webview.start()