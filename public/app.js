// Robin — minimal web client. Talks to /api/* (see api/index.py). No build
// step, no framework: plain DOM + fetch, kept genuinely minimal.

const chatLog = document.getElementById('chat-log');
const micBtn = document.getElementById('mic-btn');
const textForm = document.getElementById('text-form');
const textInput = document.getElementById('text-input');
const notifyBtn = document.getElementById('notify-btn');
const docPanel = document.getElementById('doc-panel');
const docBody = document.getElementById('doc-body');
const docClose = document.getElementById('doc-close');

let history = [];

// ---------------------------------------------------------------------------
// Device id (scopes push subscriptions only — reminders/chat are shared)
// ---------------------------------------------------------------------------

function getDeviceId() {
  let id = localStorage.getItem('device_id');
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem('device_id', id);
  }
  return id;
}

// ---------------------------------------------------------------------------
// Chat log UI
// ---------------------------------------------------------------------------

function appendMessage(role, text) {
  const el = document.createElement('div');
  el.className = `msg msg-${role}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function showDocument(text) {
  if (!text) return;
  docBody.textContent = text;
  docPanel.hidden = false;
}
docClose.addEventListener('click', () => { docPanel.hidden = true; });

// ---------------------------------------------------------------------------
// Sequential TTS playback queue (mirrors local_agent.py's speak_stream:
// fetch TTS ahead of playback, but only play one sentence at a time)
// ---------------------------------------------------------------------------

class SpeechQueue {
  constructor() {
    this.queue = [];
    this.playing = false;
  }

  push(text) {
    const blobPromise = fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }).then((r) => r.blob());
    this.queue.push(blobPromise);
    this._pump();
  }

  async _pump() {
    if (this.playing) return;
    this.playing = true;
    while (this.queue.length) {
      const blob = await this.queue.shift();
      await this._playBlob(blob);
    }
    this.playing = false;
  }

  _playBlob(blob) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
      audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
      audio.play().catch(() => resolve());
    });
  }
}

const speech = new SpeechQueue();

// ---------------------------------------------------------------------------
// Chat streaming
// ---------------------------------------------------------------------------

async function sendToChat(messages) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let assistantEl = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const rawEvent = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (!rawEvent.startsWith('data: ')) continue;

      const event = JSON.parse(rawEvent.slice(6));
      if (event.type === 'sentence') {
        if (!assistantEl) assistantEl = appendMessage('assistant', '');
        assistantEl.textContent += (assistantEl.textContent ? ' ' : '') + event.text;
        chatLog.scrollTop = chatLog.scrollHeight;
        speech.push(event.text);
      } else if (event.type === 'final') {
        history.push(event.message);
        showDocument(event.document);
      }
    }
  }
}

async function handleUserText(text) {
  if (!text || !text.trim()) return;
  appendMessage('user', text);
  history.push({ role: 'user', content: text });
  await sendToChat(history);
}

textForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = textInput.value;
  textInput.value = '';
  handleUserText(text);
});

// ---------------------------------------------------------------------------
// Mic capture (MediaRecorder -> /api/transcribe -> chat)
// ---------------------------------------------------------------------------

let mediaRecorder = null;
let recordedChunks = [];
let recording = false;

async function toggleRecording() {
  if (!recording) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstop = onRecordingStop;
    mediaRecorder.start();
    recording = true;
    micBtn.classList.add('recording');
    micBtn.textContent = '● Stop';
  } else {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    recording = false;
    micBtn.classList.remove('recording');
    micBtn.textContent = '🎤 Talk';
  }
}

async function onRecordingStop() {
  const blob = new Blob(recordedChunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('file', blob, 'audio.webm');
  const res = await fetch('/api/transcribe', { method: 'POST', body: form });
  const { text } = await res.json();
  await handleUserText(text);
}

micBtn.addEventListener('click', toggleRecording);

// ---------------------------------------------------------------------------
// Push notifications
// ---------------------------------------------------------------------------

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function enableNotifications() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    alert('Push notifications aren\'t supported in this browser. On iOS, add this page to your Home Screen first, then try again.');
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;

  const reg = await navigator.serviceWorker.register('/sw.js');
  const keyRes = await fetch('/api/push/vapid-public-key');
  const { key } = await keyRes.json();

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });

  await fetch('/api/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Device-Id': getDeviceId() },
    body: JSON.stringify({ subscription: sub.toJSON() }),
  });

  notifyBtn.textContent = 'Notifications enabled';
  notifyBtn.disabled = true;
}

notifyBtn.addEventListener('click', enableNotifications);

// ---------------------------------------------------------------------------
// Foreground reminder polling (push covers backgrounded/closed tabs; while
// the app is open, poll and both show + speak newly-due reminders)
// ---------------------------------------------------------------------------

const seenReminderIds = new Set();

async function pollDueReminders() {
  if (document.visibilityState !== 'visible') return;
  try {
    const res = await fetch('/api/reminders/today');
    const { reminders } = await res.json();
    const now = new Date();
    for (const r of reminders) {
      if (seenReminderIds.has(r.id)) continue;
      const due = new Date(r.due.replace(' ', 'T'));
      if (due <= now) {
        seenReminderIds.add(r.id);
        const text = `Reminder: ${r.text}`;
        appendMessage('assistant', text);
        speech.push(text);
      }
    }
  } catch (e) {
    // ignore transient errors, try again next tick
  }
}

setInterval(pollDueReminders, 15000);
pollDueReminders();

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
