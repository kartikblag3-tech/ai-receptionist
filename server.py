"""Osmora AI receptionist — Twilio + OpenAI Realtime server.

Call flow:
  Caller -> Twilio number -> POST /voice (returns TwiML) -> Twilio opens
  wss://<host>/media -> this server bridges Twilio Media Streams (G.711
  mu-law, 8 kHz) to OpenAI Realtime (gpt-realtime-2.1, audio/pcmu) with no
  transcoding. The model books water tests, takes messages, and the booking
  tool texts the caller an SMS appointment confirmation.

Run:
  export TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=... TWILIO_PHONE_NUMBER=+1...
  export OPENAI_API_KEY=... PUBLIC_BASE_URL=https://<public-host> OWNER_PHONE=+1...
  uvicorn server:app --host 0.0.0.0 --port 5050

Twilio needs a public HTTPS webhook and wss endpoint, so expose this with a
tunnel (ngrok / Cloudflare Tunnel) and set PUBLIC_BASE_URL to the tunnel URL.
Point the Twilio number's voice webhook at <PUBLIC_BASE_URL>/voice.
"""

import asyncio
import json
import os
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import importlib

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

import tools

load_dotenv()

# Which business this server answers for. Default is the web services
# business (webservices.py). Osmora is NOT involved in the receptionist at
# all (user, 2026-11-24). Set BUSINESS_MODULE=salon to run the hair salon
# model. The module must provide BUSINESS, MODEL, VOICE,
# build_instructions(today), TOOLS.
BUSINESS_MODULE = os.environ.get("BUSINESS_MODULE", "webservices")
biz = importlib.import_module(BUSINESS_MODULE)
# Give the tools the business config (stylist hours, per-stylist calendars)
# so availability checking can read them.
tools.configure_business(biz)

TZ = ZoneInfo("America/Toronto")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

app = FastAPI(title=f"{biz.BUSINESS['name']} AI Receptionist")


def _today_str() -> str:
    return datetime.now(TZ).strftime("%A, %B %d, %Y")


def _stream_url() -> str:
    """wss://<host>/media derived from the public base URL."""
    host = urlparse(PUBLIC_BASE_URL).netloc or "localhost:5050"
    return f"wss://{host}/media"


@app.get("/")
async def index():
    return {
        "service": f"{biz.BUSINESS['name']} AI Receptionist",
        "business": biz.BUSINESS["name"],
        "model": biz.MODEL,
        "voice": biz.VOICE,
        "public_base_url": PUBLIC_BASE_URL or "NOT SET — set PUBLIC_BASE_URL",
        "openai_key": "set" if OPENAI_API_KEY else "NOT SET",
        "twilio": "set" if tools.TWILIO_SID and tools.TWILIO_TOKEN else "NOT SET",
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/transfer")
async def transfer_endpoint(request: Request):
    """Twilio redirects a live call here when the agent transfers it to the
    owner. Dials the owner; the <Number url> is fetched the moment the owner
    picks up and played to them as a whisper before the caller is bridged."""
    kind = (request.query_params.get("kind") or "general").strip().lower()
    if kind not in ("web", "water", "it", "general"):
        kind = "general"
    owner = tools.OWNER_PHONE
    whisper_url = f"{PUBLIC_BASE_URL}/whisper?kind={kind}"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Dial>"
        f'<Number url="{whisper_url}">{owner}</Number>'
        "</Dial>"
        "</Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


@app.get("/whisper")
async def whisper_endpoint(request: Request):
    """The whisper the owner hears the moment they pick up a transferred
    call, so they know where the call came from before being connected.
    Twilio plays this TwiML to the called party only, then bridges the call."""
    kind = (request.query_params.get("kind") or "general").strip().lower()
    if kind == "web":
        text = "Web services call."
    elif kind == "water":
        text = "Water services call."
    elif kind == "it":
        text = "I. T. services call."
    else:
        text = f"{biz.BUSINESS.get('name', 'Osmora')} call."
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>{text}</Say>"
        "</Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


@app.post("/voice")
async def voice_webhook(request: Request):
    """Twilio calls this when the number rings. Return TwiML that connects
    the call audio to our media-stream WebSocket."""
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


def _session_update_event() -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": biz.MODEL,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {"type": "semantic_vad"},
                    "transcription": {"model": "gpt-4o-transcribe"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": biz.VOICE,
                },
            },
            "instructions": biz.build_instructions(_today_str()),
            "tools": biz.TOOLS,
        },
    }


async def _run_tool(name: str, args: dict, call_sid: str) -> dict:
    """Execute a tool the model asked for. Returns a dict for the model."""
    bname = biz.BUSINESS.get("name", "")
    bphone = biz.BUSINESS.get("phone", "")
    if name == "book_water_test":
        return tools.book_water_test(
            name=args.get("name", ""), phone=args.get("phone", ""),
            address=args.get("address", ""), date=args.get("date", ""),
            time=args.get("time", ""), time_text=args.get("time_text", ""),
            call_sid=call_sid,
        )
    if name == "check_availability":
        return tools.check_availability(
            service=args.get("service", ""), stylist=args.get("stylist", ""),
            date=args.get("date", ""), time=args.get("time", ""),
            duration_min=int(args.get("duration_min", 60) or 60),
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
    if name == "book_callback":
        return tools.book_callback(
            name=args.get("name", ""), phone=args.get("phone", ""),
            about=args.get("about", ""), date=args.get("date", ""),
            time=args.get("time", ""), time_text=args.get("time_text", ""),
            call_sid=call_sid,
        )
    if name == "take_message":
        return tools.take_message(
            name=args.get("name", ""), phone=args.get("phone", ""),
            message=args.get("message", ""), urgent=bool(args.get("urgent", False)),
            call_sid=call_sid,
        )
    return {"ok": False, "message": f"Unknown tool {name}."}


@app.websocket("/media")
async def media_stream(ws: WebSocket):
    """Twilio Media Streams WebSocket. Bridges Twilio <-> OpenAI Realtime."""
    await ws.accept()
    stream_sid = None
    call_sid = ""
    caller = ""
    started_at = datetime.now(TZ).isoformat()
    transcript: list = []
    tools_used: list = []
    openai_ws = None
    pump_task = None

    async def send_to_openai(event: dict):
        if openai_ws is not None:
            await openai_ws.send(json.dumps(event))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                continue

            if event == "start":
                stream_sid = msg["start"]["streamSid"]
                params = msg["start"].get("customParameters", {})
                caller = params.get("caller", "")
                call_sid = params.get("callSid", "") or msg["start"].get("callSid", "")
                # Open the OpenAI Realtime session.
                openai_ws = await websockets.connect(
                    f"wss://api.openai.com/v1/realtime?model={biz.MODEL}",
                    additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                )
                await send_to_openai(_session_update_event())
                # Start forwarding OpenAI audio/events back to Twilio.
                pump_task = asyncio.create_task(
                    _pump_openai_to_twilio(ws, openai_ws, stream_sid, call_sid,
                                           transcript, tools_used)
                )
                continue

            if event == "media":
                # Caller audio (mu-law base64) -> OpenAI, unchanged.
                payload = msg["media"]["payload"]
                await send_to_openai({"type": "input_audio_buffer.append", "audio": payload})
                continue

            if event == "dtmf":
                continue

            if event == "stop":
                break

            if event == "mark":
                continue
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 - log and still close cleanly
        print(f"[media] error: {e}")
    finally:
        # Stop the OpenAI->Twilio pump, close both sockets, then summarize.
        if pump_task is not None:
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        if openai_ws is not None:
            try:
                await openai_ws.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        if call_sid or caller:
            tools.write_call_summary(call_sid or "unknown", caller or "unknown",
                                     started_at, transcript, tools_used)


async def _pump_openai_to_twilio(twilio_ws: WebSocket, openai_ws, stream_sid: str,
                                 call_sid: str, transcript: list, tools_used: list):
    """Forward OpenAI audio + events to Twilio, and run function calls."""
    async for raw in openai_ws:
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        etype = event.get("type")

        if etype == "session.updated":
            # Greet first, like a receptionist does.
            await openai_ws.send(json.dumps({
                "type": "response.create",
                "response": {"instructions": f"Greet the caller: '{biz.GREETING}'"},
            }))
        elif etype == "response.output_audio.delta":
            # Agent audio (mu-law base64) -> Twilio, unchanged.
            await twilio_ws.send_text(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": event.get("delta", "")},
            }))
        elif etype == "response.output_audio_transcript.delta":
            transcript.append({"role": "assistant", "text": event.get("delta", "")})
        elif etype == "conversation.item.input_audio_transcription.delta":
            transcript.append({"role": "caller", "text": event.get("delta", "")})
        elif etype == "input_audio_buffer.speech_started":
            # Caller is talking over the agent — stop the audio playing.
            await twilio_ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
        elif etype == "response.function_call_arguments.done":
            name = event.get("name", "")
            try:
                args = json.loads(event.get("arguments", "{}"))
            except ValueError:
                args = {}
            result = await _run_tool(name, args, call_sid)
            tools_used.append(f"{name}: {result.get('message', '')}")
            await openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": event.get("call_id", ""),
                    "output": json.dumps(result),
                },
            }))
            await openai_ws.send(json.dumps({"type": "response.create"}))
        elif etype == "error":
            print(f"[openai] error event: {event}")
        # Other events (response.done, rate_limits.updated, etc.) need no action.
