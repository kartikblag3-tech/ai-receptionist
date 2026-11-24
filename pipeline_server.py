"""Web services AI receptionist — PIPELINE voice agent.

This is the working voice agent while the OpenAI Realtime API is locked
(the account cannot use gpt-realtime-2.1 yet). It uses only models the key
CAN access today, so it works right now:

  Caller audio (Twilio Media Streams, G.711 mu-law 8 kHz)
    -> whisper-1            (speech to text)
    -> gpt-4o-mini          (conversation + tools)
    -> gpt-4o-mini-tts      (text to speech, voice "marin")
    -> ffmpeg to mu-law 8 kHz -> back to Twilio

It is turn-based, not full-duplex like Realtime, so there is a short pause
(about 1-2 seconds) while it thinks. It is also cheaper per minute than
Realtime. When the Realtime models unlock, the server in server.py
(Realtime WebSocket) becomes the better option and the Twilio webhook can
be pointed back at it.

Auth: OpenAI calls use a surrogate from the vault (custom.openai) via
authd. The server fetches a fresh surrogate per turn, so the raw key is
never in a file or an environment variable.

Twilio webhook: point the number's voice webhook at
<PUBLIC_BASE_URL>/voice-pipeline. That returns TwiML connecting the call
audio to wss://<host>/media-pipeline.
"""

import asyncio
import base64
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

import tools

load_dotenv()

BUSINESS_MODULE = os.environ.get("BUSINESS_MODULE", "webservices")
biz = importlib.import_module(BUSINESS_MODULE)

TZ = ZoneInfo("America/Toronto")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Models the key can actually use today (verified 2026-11-24).
STT_MODEL = "whisper-1"
CHAT_MODEL = "gpt-4o-mini"
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "marin"

app = FastAPI(title=f"{biz.BUSINESS['name']} AI Receptionist (pipeline)")


def _today_str() -> str:
    return datetime.now(TZ).strftime("%A, %B %d, %Y")


def _stream_url() -> str:
    host = urlparse(PUBLIC_BASE_URL).netloc or "localhost:5050"
    return f"wss://{host}/media-pipeline"


def _openai_key() -> str:
    """Bearer token for OpenAI. On a cloud host, use the raw key from the
    OPENAI_API_KEY environment variable. On this VM, use a surrogate from
    the vault (the raw key is never in a file here). The vault import is
    lazy so the module also loads on a cloud host that has no vault."""
    raw = os.environ.get("OPENAI_API_KEY", "").strip()
    if raw:
        return raw
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import dynamic_credential_entry

    return dynamic_credential_entry("custom.openai", "access_token")["surrogate"]


def _surrogate() -> str:
    """Backwards-compatible alias — returns the OpenAI bearer token."""
    return _openai_key()


def _http_client() -> httpx.AsyncClient:
    """httpx client that works through the egress proxy. trust_env=False
    avoids a proxy-parsing bug with the bracketed IPv6 entries in NO_PROXY;
    the proxy and the egress CA bundle are set explicitly instead."""
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    verify = os.environ.get("SSL_CERT_FILE", "/run/hatch/egress-tls/ca-bundle.pem")
    return httpx.AsyncClient(timeout=60.0, trust_env=False, proxy=proxy or None,
                             verify=verify)


async def _openai_post(path: str, **kwargs) -> dict:
    """POST to OpenAI with surrogate auth. Returns the JSON body."""
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {_surrogate()}"
    async with _http_client() as client:
        resp = await client.post(f"https://api.openai.com{path}",
                                 headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()


async def _transcribe(mulaw: bytes) -> str:
    """whisper-1 speech to text. mulaw is G.711 mu-law 8 kHz audio."""
    # whisper needs a wav file; convert mu-law -> 16-bit PCM wav via ffmpeg.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "mulaw", "-ar", "8000",
             "-ac", "1", "-i", "pipe:0", "-ar", "16000", "-ac", "1", wav_path],
            input=mulaw, capture_output=True, timeout=30, check=True,
        )
        with open(wav_path, "rb") as f:
            wav_bytes = f.read()
        headers = {"Authorization": f"Bearer {_surrogate()}"}
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": STT_MODEL}
        async with _http_client() as client:
            resp = await client.post("https://api.openai.com/v1/audio/transcriptions",
                                     headers=headers, files=files, data=data)
            resp.raise_for_status()
            return (resp.json().get("text") or "").strip()
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _chat_tools() -> list:
    """Convert the Realtime-format tools (flat name/description/parameters)
    to the Chat Completions format (nested under 'function')."""
    out = []
    for t in biz.TOOLS:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return out


async def _chat(messages: list) -> dict:
    """gpt-4o-mini chat completion with tools. Returns the message dict."""
    body = {
        "model": CHAT_MODEL,
        "messages": messages,
        "tools": _chat_tools(),
        "tool_choice": "auto",
        "temperature": 0.3,
    }
    data = await _openai_post("/v1/chat/completions", json=body)
    return data["choices"][0]["message"]


async def _speak(text: str) -> bytes:
    """gpt-4o-mini-tts -> mu-law 8 kHz audio bytes for Twilio."""
    body = {"model": TTS_MODEL, "input": text, "voice": TTS_VOICE,
            "response_format": "wav"}
    headers = {"Authorization": f"Bearer {_surrogate()}"}
    async with _http_client() as client:
        resp = await client.post("https://api.openai.com/v1/audio/speech",
                                 headers=headers, json=body)
        resp.raise_for_status()
        wav_bytes = resp.content
    # wav (likely 24 kHz) -> mu-law 8 kHz for Twilio.
    out = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", "pipe:0",
         "-ar", "8000", "-ac", "1", "-f", "mulaw", "pipe:1"],
        input=wav_bytes, capture_output=True, timeout=30, check=True,
    )
    return out.stdout


def _mulaw_rms(chunk: bytes) -> float:
    """Rough loudness of a mu-law chunk (0-255 per byte, 128 is silence)."""
    if not chunk:
        return 0.0
    return sum(abs(b - 128) for b in chunk) / len(chunk)


@app.get("/")
async def index():
    return {
        "service": f"{biz.BUSINESS['name']} AI Receptionist (pipeline)",
        "business": biz.BUSINESS["name"],
        "model": "pipeline: whisper-1 + gpt-4o-mini + gpt-4o-mini-tts",
        "public_base_url": PUBLIC_BASE_URL or "NOT SET — set PUBLIC_BASE_URL",
        "twilio": "set" if tools.TWILIO_SID and tools.TWILIO_TOKEN else "NOT SET",
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/voice-pipeline")
async def voice_webhook(request: Request):
    """Twilio calls this when the number rings. Return TwiML that connects
    the call audio to the pipeline media-stream WebSocket."""
    form = await request.form()
    caller = form.get("From", "")
    call_sid = form.get("CallSid", "")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{_stream_url()}">'
        f'<Parameter name="caller" value="{caller}"/>'
        f'<Parameter name="callSid" value="{call_sid}"/>'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


@app.websocket("/media-pipeline")
async def media_pipeline(ws: WebSocket):
    """Twilio Media Streams WebSocket, pipeline mode."""
    await ws.accept()
    stream_sid = None
    call_sid = ""
    caller = ""
    started_at = datetime.now(TZ).isoformat()
    transcript: list = []
    tools_used: list = []
    # Conversation history for gpt-4o-mini.
    messages = [
        {"role": "system", "content": biz.build_instructions(_today_str())},
    ]
    # Audio buffering / turn detection.
    audio_buf = bytearray()
    last_speech = 0.0
    speaking = False
    # True while we are playing agent audio; caller speech then is barge-in.
    playing = False
    stop_play = asyncio.Event()
    greeted = False

    async def send_audio(mulaw: bytes):
        """Stream mu-law audio to Twilio in 20 ms frames (160 bytes)."""
        nonlocal playing
        playing = True
        stop_play.clear()
        try:
            for i in range(0, len(mulaw), 160):
                if stop_play.is_set():
                    break
                frame = mulaw[i:i + 160]
                await ws.send_text(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(frame).decode()},
                }))
                await asyncio.sleep(0.02)
        finally:
            playing = False

    async def run_tool(name: str, args: dict) -> dict:
        bname = biz.BUSINESS.get("name", "")
        bphone = biz.BUSINESS.get("phone", "")
        if name == "book_callback":
            return tools.book_callback(
                name=args.get("name", ""), phone=args.get("phone", ""),
                about=args.get("about", ""), date=args.get("date", ""),
                time=args.get("time", ""), time_text=args.get("time_text", ""),
                call_sid=call_sid,
            )
        if name == "book_water_test":
            return tools.book_water_test(
                name=args.get("name", ""), phone=args.get("phone", ""),
                address=args.get("address", ""), date=args.get("date", ""),
                time=args.get("time", ""), time_text=args.get("time_text", ""),
                call_sid=call_sid,
            )
        if name == "book_appointment":
            return tools.book_appointment(
                business_name=bname, business_phone=bphone,
                service=args.get("service", ""), stylist=args.get("stylist", ""),
                name=args.get("name", ""), phone=args.get("phone", ""),
                date=args.get("date", ""), time=args.get("time", ""),
                duration_min=int(args.get("duration_min", 60) or 60),
                time_text=args.get("time_text", ""), call_sid=call_sid,
            )
        if name == "reschedule_appointment":
            return tools.reschedule_appointment(
                business_name=bname, business_phone=bphone,
                name=args.get("name", ""), phone=args.get("phone", ""),
                old_date=args.get("old_date", ""), old_time=args.get("old_time", ""),
                new_date=args.get("new_date", ""), new_time=args.get("new_time", ""),
                call_sid=call_sid,
            )
        if name == "cancel_appointment":
            return tools.cancel_appointment(
                business_name=bname, business_phone=bphone,
                name=args.get("name", ""), phone=args.get("phone", ""),
                date=args.get("date", ""), time=args.get("time", ""),
                call_sid=call_sid,
            )
        if name == "transfer_to_owner":
            return tools.transfer_to_owner(
                call_sid=call_sid, kind=args.get("kind", "general"),
            )
        if name == "take_message":
            return tools.take_message(
                name=args.get("name", ""), phone=args.get("phone", ""),
                message=args.get("message", ""), urgent=bool(args.get("urgent", False)),
                call_sid=call_sid,
            )
        return {"ok": False, "message": f"Unknown tool {name}."}

    async def handle_turn():
        """Transcribe the buffered caller audio, get a reply, speak it."""
        nonlocal audio_buf
        if len(audio_buf) < 800:  # less than 0.1s — ignore
            audio_buf = bytearray()
            return
        audio = bytes(audio_buf)
        audio_buf = bytearray()
        try:
            text = await _transcribe(audio)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] transcribe failed: {e}")
            return
        if not text:
            return
        transcript.append({"role": "caller", "text": text})
        messages.append({"role": "user", "content": text})
        # Ask the model; run tools until it gives a plain reply.
        reply_text = ""
        for _ in range(4):
            try:
                msg = await _chat(messages)
            except Exception as e:  # noqa: BLE001
                print(f"[pipeline] chat failed: {e}")
                return
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                reply_text = msg.get("content") or ""
                break
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except ValueError:
                    args = {}
                result = await run_tool(fn.get("name", ""), args)
                tools_used.append(f"{fn.get('name', '')}: {result.get('message', '')}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result),
                })
            # If a transfer happened, the call is being redirected; stop.
            if any("Transferring the call" in (t or "") for t in tools_used[-len(tool_calls):]):
                return
        if not reply_text:
            return
        transcript.append({"role": "assistant", "text": reply_text})
        try:
            audio_out = await _speak(reply_text)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] tts failed: {e}")
            return
        await send_audio(audio_out)

    async def silence_watch():
        """End the caller's turn after ~1.2s of silence following speech."""
        nonlocal speaking
        while True:
            await asyncio.sleep(0.2)
            if speaking and audio_buf and (time.time() - last_speech > 1.2):
                speaking = False
                await handle_turn()

    watch_task = None
    try:
        watch_task = asyncio.create_task(silence_watch())
        while True:
            raw = await ws.receive_text()
            event = json.loads(raw).get("event")

            if event == "start":
                stream_sid = json.loads(raw)["start"]["streamSid"]
                params = json.loads(raw)["start"].get("customParameters", {})
                caller = params.get("caller", "")
                call_sid = params.get("callSid", "") or json.loads(raw)["start"].get("callSid", "")
                # Greet first.
                if not greeted:
                    greeted = True
                    try:
                        audio_out = await _speak(biz.GREETING)
                        await send_audio(audio_out)
                    except Exception as e:  # noqa: BLE001
                        print(f"[pipeline] greeting tts failed: {e}")
                continue

            if event == "media":
                payload = base64.b64decode(json.loads(raw)["media"]["payload"])
                rms = _mulaw_rms(payload)
                if rms > 4:  # speech (not silence)
                    if playing:
                        # Barge-in: caller spoke over the agent — stop playback.
                        stop_play.set()
                        await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
                    last_speech = time.time()
                    speaking = True
                    audio_buf.extend(payload)
                elif speaking:
                    # Silence while a turn is open — keep buffering a little
                    # so the silence window is measured from last speech.
                    audio_buf.extend(payload)
                continue

            if event == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] error: {e}")
    finally:
        if watch_task is not None:
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        if call_sid or caller:
            tools.write_call_summary(call_sid or "unknown", caller or "unknown",
                                     started_at, transcript, tools_used)
