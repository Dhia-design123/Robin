"""
Single FastAPI ASGI app — the one Vercel entrypoint (see vercel.json) for the
whole cloud backend: chat, transcription, TTS, reminders, push notifications,
and the due-reminders cron job. Everything shares one OpenAI client, one
Supabase client, one VAPID config, so this is deliberately one app rather
than many small per-route functions.
"""

import json
from datetime import datetime

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from friday.cloud.config import cloud_config
from friday.cloud import db_push, push
from friday.cloud.llm import stream_chat
from friday.cloud.stt import transcribe_bytes
from friday.cloud.tts import generate_tts_stream
from friday.db import reminders as reminders_db

app = FastAPI(title="Robin Cloud API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Chat / voice
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def event_stream():
        async for event in stream_chat(req.messages):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    text = transcribe_bytes(audio_bytes, filename=file.filename or "audio.webm")
    return {"text": text}


class TTSRequest(BaseModel):
    text: str


@app.post("/api/tts")
async def tts(req: TTSRequest):
    return StreamingResponse(generate_tts_stream(req.text), media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Reminders (shared with the desktop app via friday/db/reminders.py)
# ---------------------------------------------------------------------------

class ReminderCreate(BaseModel):
    text: str
    due_datetime: str


@app.get("/api/reminders")
async def list_reminders():
    return {"reminders": reminders_db.list_reminders()}


@app.post("/api/reminders")
async def create_reminder(req: ReminderCreate):
    try:
        due = datetime.strptime(req.due_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "due_datetime must be in 'YYYY-MM-DD HH:MM' format")
    return reminders_db.create_reminder(req.text, due)


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int):
    reminders_db.delete_reminder(reminder_id)
    return {"deleted": True}


@app.get("/api/reminders/today")
async def todays_reminders():
    return {"reminders": reminders_db.list_todays_reminders()}


# ---------------------------------------------------------------------------
# Web Push
# ---------------------------------------------------------------------------

class PushSubscribeRequest(BaseModel):
    subscription: dict


@app.get("/api/push/vapid-public-key")
async def vapid_public_key():
    return {"key": cloud_config.VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
async def push_subscribe(req: PushSubscribeRequest, x_device_id: str = Header(...)):
    db_push.upsert_subscription(x_device_id, req.subscription)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cron: due-reminder check + push delivery (Vercel Cron hits this, see vercel.json)
# ---------------------------------------------------------------------------

@app.api_route("/api/cron/due-reminders", methods=["GET", "POST"])
async def cron_due_reminders(authorization: str = Header(default="")):
    expected = f"Bearer {cloud_config.CRON_SECRET}"
    if not cloud_config.CRON_SECRET or authorization != expected:
        raise HTTPException(401, "Unauthorized")

    due = reminders_db.list_all_due(datetime.now())
    notified = 0
    for r in due:
        sent = push.notify_all_devices("Robin Reminder", r["text"])
        notified += sent
        reminders_db.mark_done(r["id"])

    return {"checked": len(due), "notified": notified}
