"""
Speech-to-text — ports local_agent.py's transcribe() for the cloud API: takes
raw audio bytes (from a browser MediaRecorder upload) instead of a mic-fed
BytesIO, everything else is the same OpenAI call.
"""

import io
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def transcribe_bytes(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    result = _client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=buf,
    )
    return result.text.strip()
