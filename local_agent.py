"""
Robin — Local Voice Agent (no LiveKit, no browser)
Mic -> Whisper (STT) -> GPT-4o (LLM) -> OpenAI TTS -> Speakers
"""

import os
import io
import wave
import time
import json
import tempfile
import asyncio
import numpy as np
import sounddevice as sd
import re
import queue
import threading
import keyboard
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from playsound import playsound
from mcp import ClientSession
from mcp.client.sse import sse_client
import hud_web as hud
from win11toast import toast
from friday.db import reminders as reminders_db



load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MCP_SERVER_URL = "http://127.0.0.1:8000/sse"

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 500      # lower = more sensitive to quiet sounds
SILENCE_DURATION = .7       # seconds of silence before we consider you "done"
CHUNK_DURATION = 0.1         # seconds per audio chunk we check

SYSTEM_PROMPT = """
You are Robin — Tony Stark's AI, now serving your user.
You are calm, composed, and sharp. Speak like a trusted aide.
Keep responses short: two to four sentences max. No lists, no markdown.
If the user's speech is unclear or just filler sounds, ask them to repeat or clarify.
Address the user as "sir" naturally and consistently — for example, work it into
greetings, confirmations, and responses, the way a butler or trusted aide would
(e.g. "Right away, sir", "Good morning, sir", "Understood, sir"). Don't force it
into every single sentence, but it should come up regularly and feel natural, not
like a template.
Keep responses short: two to six sentences max. No lists, no markdown.
If the user's speech is unclear or just filler sounds, ask them to repeat or clarify.

If the user asks for a recipe, instructions, a how-to guide, a plan, or anything
that would benefit from full written details, use the create_task_document tool.
Don't try to speak out all the details yourself — let that tool handle writing
the full version, and just relay its short summary back to the user.

If the user asks to set a reminder, use the set_reminder tool. The current date and
time will be provided at the start of their message in brackets — use that exact
value as your reference point, not any other date. Convert what they say (like
"in 30 minutes" or "tomorrow at 3pm") into YYYY-MM-DD HH:MM format based on that
real current time. Always confirm the reminder back to them clearly after setting it.

When the user says "good morning" (with or without "Robin"), do the following in order:
1. Call list_todays_reminders to see what's scheduled today
2. Call get_world_finance_news to check on markets
3. Call workspace_launch to open their daily apps and folders
4. Greet them warmly, briefly summarize today's tasks/reminders, briefly summarize
   the market/finance situation, mention you've opened their workspace, and end by
   asking "What will we be working on today, sir?"
Keep the whole thing concise — this is spoken aloud, not read. Aim for 6-8 sentences total,
not a long report.

""".strip()

conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------

recorder = None
mcp_runner = None

class MCPAsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


class AudioRecorder:
    def __init__(self, sample_rate: int, chunk_duration: float):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.stream = sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16')
        self.stream.start()

    def read_chunk(self):
        data, _ = self.stream.read(self.chunk_samples)
        return data

    def cleanup(self):
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# MCP tool bridge
# ---------------------------------------------------------------------------

mcp_tools_cache = []
muted = False
pending_reminder_texts = []
is_robin_speaking = False


async def _mcp_list_tools_async():
    async with sse_client(MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            schemas = []
            for t in tools_result.tools:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    }
                })
            return schemas


async def _mcp_call_tool_async(name, arguments):
    async with sse_client(MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            parts = []
            for c in result.content:
                if hasattr(c, "text"):
                    parts.append(c.text)
            return "\n".join(parts) if parts else "(no output)"

def toggle_mute():
    global muted
    muted = not muted
    status = "🔇 MUTED" if muted else "🔊 UNMUTED"
    print(f"\n{status}")
    hud.set_muted(muted)

def load_mcp_tools():
    global mcp_tools_cache, mcp_runner
    if mcp_runner is None:
        mcp_runner = MCPAsyncRunner()

    try:
        mcp_tools_cache = mcp_runner.run(_mcp_list_tools_async())
        print(f"🔧 Loaded {len(mcp_tools_cache)} MCP tools: "
              f"{[t['function']['name'] for t in mcp_tools_cache]}")
    except Exception as e:
        print(f"⚠️  Could not load MCP tools ({e}). Continuing without tools.")
        mcp_tools_cache = []


def call_mcp_tool(name, arguments):
    try:
        return mcp_runner.run(_mcp_call_tool_async(name, arguments))
    except Exception as e:
        return f"Tool '{name}' failed: {e}"


def record_until_silence():
    """Records from mic until it detects a pause after speech."""
    print("\n🎤 Listening...")
    silence_chunks_needed = int(SILENCE_DURATION / CHUNK_DURATION)

    buffer = []
    silence_count = 0
    started_speaking = False

    while True:
        data = recorder.read_chunk()
        volume = np.abs(data).mean()
        buffer.append(data.copy())

        if volume > SILENCE_THRESHOLD:
            started_speaking = True
            silence_count = 0
        elif started_speaking:
            silence_count += 1

        if started_speaking and silence_count >= silence_chunks_needed:
            break

        if len(buffer) > int(20 / CHUNK_DURATION):
            break

    if not buffer:
        return np.empty((0,), dtype=np.int16)

    audio = np.concatenate(buffer, axis=0)

    # Trim trailing silence before sending to Whisper (reduces hallucination)
    trim_samples = int(SAMPLE_RATE * (SILENCE_DURATION - 0.3))
    if trim_samples > 0 and audio.shape[0] > trim_samples:
        audio = audio[:-trim_samples]

    return audio


def audio_to_wav_bytes(audio):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    buf.seek(0)
    buf.name = "audio.wav"
    return buf


def transcribe(audio_buf):
    result = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=audio_buf,
    )
    return result.text.strip()



def get_response_streaming(user_text):
    """Streams the LLM response and yields complete sentences as they're ready."""
    context = get_current_datetime_context()
    conversation.append({"role": "user", "content": f"[{context}]\n{user_text}"})

    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation,
        tools=mcp_tools_cache if mcp_tools_cache else None,
        stream=True,
    )

    buffer = ""
    full_reply = ""
    tool_calls_accum = {}

    for chunk in stream:
        delta = chunk.choices[0].delta

        # Handle tool call streaming (accumulate, don't speak these)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_accum:
                    tool_calls_accum[idx] = {"id": tc.id, "name": "", "arguments": ""}
                if tc.function.name:
                    tool_calls_accum[idx]["name"] += tc.function.name
                if tc.function.arguments:
                    tool_calls_accum[idx]["arguments"] += tc.function.arguments
            continue

        if delta.content:
            buffer += delta.content
            full_reply += delta.content

            # Check for a complete sentence in the buffer
            match = re.search(r'([.?!])(\s|$)', buffer)
            if match:
                end = match.end()
                sentence = buffer[:end].strip()
                buffer = buffer[end:]
                if sentence:
                    yield ("sentence", sentence)

    # Yield any leftover text as a final sentence
    if buffer.strip():
        yield ("sentence", buffer.strip())

    # If there were tool calls, handle them after streaming completes
    if tool_calls_accum:
        conversation.append({
            "role": "assistant",
            "content": full_reply or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]}
                }
                for tc in tool_calls_accum.values()
            ]
        })
        for tc in tool_calls_accum.values():
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"🔧 Calling tool: {tc['name']}({args})")
            result = call_mcp_tool(tc["name"], args)
            conversation.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

        # Stream the follow-up response after tool results, sentence by sentence
        yield from _stream_followup()
    else:
        conversation.append({"role": "assistant", "content": full_reply})


def _stream_followup():
    """Streams the follow-up response after tool results are added."""
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation,
        stream=True,
    )
    buffer = ""
    full_reply = ""
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            buffer += delta.content
            full_reply += delta.content
            match = re.search(r'([.?!])(\s|$)', buffer)
            if match:
                end = match.end()
                sentence = buffer[:end].strip()
                buffer = buffer[end:]
                if sentence:
                    yield ("sentence", sentence)
    if buffer.strip():
        yield ("sentence", buffer.strip())
    conversation.append({"role": "assistant", "content": full_reply})

def get_current_datetime_context():
    now = datetime.now()
    return f"Current date and time: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A, %B %d, %Y')})"




def generate_tts(text):
    """Generates TTS audio for a sentence and returns the filename. Does NOT play it."""
    fd, filename = tempfile.mkstemp(prefix="_temp_reply_", suffix=".mp3")
    os.close(fd)
    try:
        with client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="echo",
            input=text,
        ) as response:
            response.stream_to_file(filename)
        return filename
    except Exception:
        try:
            os.remove(filename)
        except OSError:
            pass
        raise


def play_audio(filename):
    """Plays an audio file and cleans it up afterward."""
    hud.set_speaking(True)
    playsound(filename)
    hud.set_speaking(False)
    try:
        os.remove(filename)
    except Exception:
        pass


def speak_stream(sentence_generator):
    """Consumes streamed sentences, generating TTS ahead of playback for smoother flow."""
    global is_robin_speaking
    is_robin_speaking = True

    audio_queue = queue.Queue()
    done = threading.Event()

    def producer():
        for kind, sentence in sentence_generator:
            print(f"🗣️  Robin: {sentence}")
            filename = generate_tts(sentence)
            audio_queue.put(filename)
        done.set()

    t = threading.Thread(target=producer, daemon=True)
    t.start()

    while not (done.is_set() and audio_queue.empty()):
        try:
            filename = audio_queue.get(timeout=0.1)
            play_audio(filename)
        except queue.Empty:
            continue

    is_robin_speaking = False

    # After finishing, check if any reminders piled up while talking
    if pending_reminder_texts:
        texts = pending_reminder_texts.copy()
        pending_reminder_texts.clear()
        for text in texts:
            announce_reminder(text)

def announce_reminder(text):
    try:
        reminder_prompt = f"Naturally remind the user about this task in your own voice, as Robin: {text}. Keep it to one short sentence."
        speak_stream(get_response_streaming(reminder_prompt))
    except Exception:
        pass

def listen_for_wake_word():
    """Continuously listens at low overhead until it hears 'Robin', then returns the transcript."""
    print("\n💤 Idle — say 'Robin' to wake me up...")
    silence_chunks_needed = int(1.0 / CHUNK_DURATION)

    while True:
        if muted:
            time.sleep(0.3)
            continue

        buffer = []
        silence_count = 0
        started_speaking = False

        while True:
            data = recorder.read_chunk()
            volume = np.abs(data).mean()
            buffer.append(data.copy())

            if volume > SILENCE_THRESHOLD:
                started_speaking = True
                silence_count = 0
            elif started_speaking:
                silence_count += 1

            if started_speaking and silence_count >= silence_chunks_needed:
                break

            if len(buffer) > int(6 / CHUNK_DURATION):
                break

        if not started_speaking:
            continue

        audio = np.concatenate(buffer, axis=0)
        if audio.shape[0] < SAMPLE_RATE * 0.3:
            continue

        wav_buf = audio_to_wav_bytes(audio)
        try:
            text = transcribe(wav_buf)
        except Exception:
            continue

        if text and "robin" in text.lower():
            print(f"👂 Wake word detected: \"{text}\"")
            return text   # <-- return the transcript instead of nothing

def record_until_silence_or_timeout(max_wait_seconds):
    """Like record_until_silence, but gives up and returns None if nothing is said within max_wait_seconds."""
    silence_chunks_needed = int(SILENCE_DURATION / CHUNK_DURATION)
    max_wait_chunks = int(max_wait_seconds / CHUNK_DURATION)

    buffer = []
    silence_count = 0
    started_speaking = False
    waited_chunks = 0

    while True:
        data = recorder.read_chunk()
        volume = np.abs(data).mean()

        if not started_speaking:
            waited_chunks += 1
            if waited_chunks > max_wait_chunks:
                return None  # timed out waiting for speech

        buffer.append(data.copy())

        if volume > SILENCE_THRESHOLD:
            started_speaking = True
            silence_count = 0
        elif started_speaking:
            silence_count += 1

        if started_speaking and silence_count >= silence_chunks_needed:
            break

        if len(buffer) > int(20 / CHUNK_DURATION):
            break

    audio = np.concatenate(buffer, axis=0)
    trim_samples = int(SAMPLE_RATE * (SILENCE_DURATION - 0.3))
    if trim_samples > 0 and audio.shape[0] > trim_samples:
        audio = audio[:-trim_samples]

    return audio

ACTIVE_SESSION_TIMEOUT = 90

def check_reminders_loop():
    """Background thread: checks for due reminders (via the shared Supabase store) and announces them."""
    while True:
        time.sleep(20)

        try:
            due_reminders = reminders_db.list_all_due(datetime.now())
        except Exception as e:
            print(f"⚠️  Couldn't check reminders ({e}).")
            continue

        for r in due_reminders:
            text = r["text"]
            print(f"\n🔔 Reminder due: {text}")

            try:
                _ = toast("Robin Reminder", text)
            except Exception:
                pass

            if is_robin_speaking:
                pending_reminder_texts.append(text)
            else:
                announce_reminder(text)

            try:
                reminders_db.mark_done(r["id"])
            except Exception:
                pass


def shutdown_resources():
    global recorder, mcp_runner
    try:
        if recorder is not None:
            recorder.cleanup()
    except Exception:
        pass

    try:
        if mcp_runner is not None:
            mcp_runner.stop()
    except Exception:
        pass


def main():
    global recorder, mcp_runner
    mcp_runner = MCPAsyncRunner()
    recorder = AudioRecorder(SAMPLE_RATE, CHUNK_DURATION)
    load_mcp_tools()
    keyboard.add_hotkey('ctrl+shift+m', toggle_mute)
    
    reminder_thread = threading.Thread(target=check_reminders_loop, daemon=True)
    reminder_thread.start()
    print("=" * 50)
    print("Robin is online. Say 'Robin' to start talking. Ctrl+C to stop.")
    print("=" * 50)

    try:
        while True:
            wake_text = listen_for_wake_word()

            if muted:
                continue

            remainder = re.sub(r'\bRobin\b', '', wake_text, flags=re.IGNORECASE).strip(" ,.!?")

            if len(remainder) > 3:
                user_text = remainder
                print(f"👤 You: {user_text}")
            else:
                audio = record_until_silence()
                if audio.shape[0] < SAMPLE_RATE * 0.3:
                    continue
                wav_buf = audio_to_wav_bytes(audio)
                user_text = transcribe(wav_buf)
                if not user_text or len(user_text.strip()) < 2:
                    print("(didn't catch that)")
                    continue
                print(f"👤 You: {user_text}")

            speak_stream(get_response_streaming(user_text))

            # --- Active session: keep listening without needing "Robin" again ---
            last_active = time.time()
            while time.time() - last_active < ACTIVE_SESSION_TIMEOUT:
                if muted:
                    break

                remaining_time = ACTIVE_SESSION_TIMEOUT - (time.time() - last_active)
                audio = record_until_silence_or_timeout(remaining_time)

                if audio is None:
                    print("\n💤 Session timed out — back to idle.")
                    break

                if audio.shape[0] < SAMPLE_RATE * 0.3:
                    continue

                wav_buf = audio_to_wav_bytes(audio)
                user_text = transcribe(wav_buf)

                if not user_text or len(user_text.strip()) < 2:
                    continue

                print(f"👤 You: {user_text}")
                speak_stream(get_response_streaming(user_text))
                last_active = time.time()

    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        shutdown_resources()







if __name__ == "__main__":
    hud.create_window()

    # Run the voice agent loop in a background thread
    agent_thread = threading.Thread(target=main, daemon=True)
    agent_thread.start()

    # Webview must run on the main thread — this blocks here
    hud.start_blocking()