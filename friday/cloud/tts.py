"""
Text-to-speech — ports local_agent.py's generate_tts() for the cloud API:
streams mp3 bytes straight through instead of writing a temp file (Vercel's
/tmp is ephemeral/limited and there's no reason to hit disk for this).
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_tts_stream(text: str):
    """Yields mp3 byte chunks for the given text. Same model/voice as the desktop app."""
    with _client.audio.speech.with_streaming_response.create(
        model="tts-1",
        voice="echo",
        input=text,
    ) as response:
        for chunk in response.iter_bytes():
            yield chunk
