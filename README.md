# AI Receptionist — Custom Twilio + OpenAI (cheapest per call)

A phone receptionist for local businesses. **First market: hair salons.**
The receptionist answers **only for the user's web services business**
(Osmora is out entirely — see the pivot note below). The agent answers
calls, books callbacks, takes messages, transfers urgent calls to the
owner, and a short call summary is texted to the owner after every call.

**Pivot (2026-11-24):** Osmora/water is OUT of the receptionist entirely.
The receptionist is ONLY for the user's web services business, on the new
Twilio number **+1 (437) 747-8124**. The old Osmora number is not used.
`webservices.py` is the server default; `osmora.py` is archived.

## Which business is it answering for?

Set `BUSINESS_MODULE` to pick the config:

```bash
BUSINESS_MODULE=webservices ./venv/bin/uvicorn pipeline_server:app --host 0.0.0.0 --port 5050   # web services (default)
BUSINESS_MODULE=salon ./venv/bin/uvicorn pipeline_server:app --host 0.0.0.0 --port 5050        # hair salon
```

Each business has its own config module with its services, prices, system
prompt, greeting and tools. To onboard a new salon, copy `salon.py` to
`salon_<name>.py`, fill in the real details, and run with
`BUSINESS_MODULE=salon_<name>`.

## How it works

Two voice engines, same tools and configs:

- **Pipeline (pipeline_server.py, `/voice-pipeline` + `/media-pipeline`) —
  the working one.** Caller audio (Twilio Media Streams, G.711 μ-law,
  8 kHz) → **whisper-1** (speech to text) → **gpt-4o-mini** (conversation
  + tools) → **gpt-4o-mini-tts** (speech, voice "marin") → ffmpeg to
  μ-law 8 kHz → back to Twilio. Turn-based, so there is a short pause
  (about 1–2 s) while it thinks; it is also **cheaper per minute than
  Realtime**. It confirms every booking detail back before booking
  (spells the name, reads the phone digit by digit, repeats date/time).
  **Tested 2026-11-24**: chat, TTS, STT round-trip (perfect), and the
  book_callback flow (confirm → book) all work. Point the Twilio voice
  webhook at `<PUBLIC_BASE_URL>/voice-pipeline` to go live on it.
- **Realtime (server.py, `/voice` + `/media`) — blocked for now.** Bridges
  Twilio Media Streams to OpenAI Realtime (`gpt-realtime-2.1`, `audio/pcmu`)
  with no transcoding. **BLOCKED as of 2026-11-24**: the account cannot
  access the Realtime models yet (the key is set to "All" permissions and
  the user paid for credits, but the models still return "does not exist
  or you do not have access to it" — most likely a delay in the account
  tier updating after the purchase). When it unlocks, point the Twilio
  webhook back at `<PUBLIC_BASE_URL>/voice` for lower latency.

## Files

- `server.py` — FastAPI app (Realtime): `/voice` webhook, `/media`
  WebSocket bridge, OpenAI Realtime session, function calling, call
  summaries. **Blocked until the Realtime models unlock.**
- `pipeline_server.py` — FastAPI app (pipeline, the working one):
  `/voice-pipeline` webhook, `/media-pipeline` WebSocket, whisper-1 +
  gpt-4o-mini + gpt-4o-mini-tts, function calling, call summaries.
- `webservices.py` — business config (default): web services only.
- `salon.py` — business config: hair salon template (SAMPLE prices).
- `osmora.py` — ARCHIVED. Osmora is out of the receptionist entirely.
- `tools.py` — booking, messages, transfers (with whisper), SMS, call
  summaries. All records append to `data/*.jsonl`.
- `.env.example` — copy to `.env` and fill in.

## Setup (user does this, ~10 minutes)

1. **Twilio** — sign up at twilio.com with your name and card. Buy a phone
   number (about $1.15/mo + usage). Copy the Account SID and Auth Token from
   the console into `.env` (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_PHONE_NUMBER`).
2. **OpenAI** — sign up at platform.openai.com, add your card, create an API
   key. The key is connected to Muse via the secure connector
   (custom.openai) and the server uses it through a surrogate, so the raw
   key is never in a file. The pipeline (whisper-1 + gpt-4o-mini +
   gpt-4o-mini-tts) works with the key today. The Realtime models
   (`gpt-realtime-2.1`) are still locked on this account — most likely a
   delay after the credit purchase; re-check before switching to `server.py`.
3. **Expose the server** — Twilio needs a public HTTPS webhook and `wss`
   endpoint. Run a tunnel (ngrok or Cloudflare Tunnel) pointing at
   `localhost:5050` and put its URL in `.env` as `PUBLIC_BASE_URL`
   (e.g. `https://abc123.ngrok.io`).
4. **Owner phone** — put your mobile in `.env` as `OWNER_PHONE` to get a
   text summary after every call.
5. **Google Calendar (optional, for bookings on the calendar)** — connect
   Google Calendar in Muse. Until it is connected, bookings are still
   recorded and the caller still gets the SMS confirmation; only the calendar
   event is skipped.
6. **Point Twilio at the server** — in the Twilio console, set the number's
   voice webhook to `<PUBLIC_BASE_URL>/voice-pipeline` (HTTP POST) for the
   pipeline agent. When the Realtime models unlock, switch it to
   `<PUBLIC_BASE_URL>/voice` for the Realtime agent.
7. **Answer the open questions** in
   `../goals/ai-receptionist-for-local-businesses/files/Web_Services_Receptionist_Model.md`
   — the business name, the services offered, prices (if the agent should
   quote them), email, website, hours, and which calendar. The agent never
   guesses at these.

## Run

```bash
cd ~/workspace/ai-receptionist
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 5050
```

Check `http://localhost:5050/` — it reports whether the keys are set.
Test by calling the Twilio number.

## Costs (estimates — verify at account setup)

- OpenAI `gpt-realtime-2.1`: roughly $0.30–$0.60 per 3-minute call.
- Twilio: ~$0.02/min voice + ~$0.008 per SMS, plus ~$1.15/mo for the number.
- At ~100 calls/month: roughly $30–60/month in costs. Charge businesses
  $200–$400/month per business.

## What the agent never does

Never invents a price, warranty, service interval, or business hour. Never
claims a town's water is unsafe. Never takes payment or offers a discount.

## Voice recognition — non-native English speakers

Most callers will not be native English speakers. The agent is built for
that: it speaks slowly and clearly, uses simple words, is patient with
accents, and confirms every booking detail back (spelled name, phone number
digit by digit, date and time) before booking. If the caller speaks another
language, it replies in that language. Call transcription uses the more
accurate `gpt-4o-transcribe` model rather than the cheaper mini, for better
accent recognition. The voice model uses semantic voice-activity detection,
which waits for a complete thought instead of cutting a caller off
mid-sentence when they pause.
