"""Tools the receptionist can call during a live call.

- book_water_test: records the booking, tries to add a Google Calendar event
  (best effort — the calendar connector may not be linked yet), and texts the
  caller an SMS appointment confirmation via Twilio.
- take_message: records a message for the owner.
- send_sms: Twilio SMS helper used by the booking tool.
- write_call_summary: appends the call record (transcript + tools used) to
  calls.jsonl and, if OWNER_PHONE is set, texts the owner a short summary.

All writes are append-only JSONL so a crashed call never loses earlier data.
Secrets come from environment variables only — never hard-code them here.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from twilio.rest import Client

# Load the .env here, before reading any credentials below. server.py
# imports this module before it calls load_dotenv itself, so relying on
# the server to load the file would leave every credential empty.
load_dotenv()

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

TZ = ZoneInfo("America/Toronto")

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")
OWNER_PHONE = os.environ.get("OWNER_PHONE", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
# The number callers reached (the receptionist's Twilio number) — used as the
# callback number in SMS confirmations. The old 1-866-290-7873 Osmora number
# is kept separate and is NOT part of this system.
BUSINESS_PHONE = TWILIO_NUMBER

GWS_CLI = "/opt/hatch/bin/hatch_gws_cli"


def _twilio() -> Client:
    return Client(TWILIO_SID, TWILIO_TOKEN)


def _append(filename: str, record: dict) -> None:
    record["recorded_at"] = datetime.now(TZ).isoformat()
    with open(DATA / filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def send_sms(to: str, body: str) -> dict:
    """Send an SMS via Twilio. Returns {ok, sid or error}."""
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_NUMBER):
        return {"ok": False, "error": "Twilio credentials not configured"}
    try:
        msg = _twilio().messages.create(to=to, from_=TWILIO_NUMBER, body=body)
        return {"ok": True, "sid": msg.sid}
    except Exception as e:  # noqa: BLE001 - surface the real error to the log
        return {"ok": False, "error": str(e)}


def _calendar_insert(summary: str, start: datetime, end: datetime, description: str) -> dict:
    """Best-effort Google Calendar event via the connected-account CLI.
    Returns {ok, event_id or error}. Never raises — a missing calendar link
    must not break a booking."""
    try:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        out = subprocess.run(
            [GWS_CLI, "calendar", "events", "insert",
             "--params", json.dumps({"calendarId": "primary"}),
             "--json", json.dumps(body)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout) if out.stdout.strip() else {}
        if data.get("ok") and data.get("id"):
            return {"ok": True, "event_id": data["id"]}
        return {"ok": False, "error": data.get("error") or out.stderr.strip() or "unknown"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _calendar_patch(event_id: str, start: datetime, end: datetime) -> dict:
    """Best-effort move of a calendar event. Never raises."""
    try:
        body = {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        out = subprocess.run(
            [GWS_CLI, "calendar", "events", "patch",
             "--params", json.dumps({"calendarId": "primary", "eventId": event_id, "sendUpdates": "all"}),
             "--json", json.dumps(body)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout) if out.stdout.strip() else {}
        if data.get("ok"):
            return {"ok": True, "event_id": event_id}
        return {"ok": False, "error": data.get("error") or out.stderr.strip() or "unknown"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _calendar_delete(event_id: str) -> dict:
    """Best-effort delete of a calendar event. Never raises."""
    try:
        out = subprocess.run(
            [GWS_CLI, "calendar", "events", "delete",
             "--params", json.dumps({"calendarId": "primary", "eventId": event_id, "sendUpdates": "all"})],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout) if out.stdout.strip() else {}
        if data.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": data.get("error") or out.stderr.strip() or "unknown"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _find_booking_event_id(phone: str, date: str, time: str, filename: str = "appointments.jsonl"):
    """Find the calendar event id of a recorded booking by phone+date+time."""
    path = DATA / filename
    if not path.exists():
        return None
    digits = "".join(c for c in phone if c.isdigit())
    for line in reversed(open(path, encoding="utf-8").readlines()):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("date") == date and rec.get("time") == time:
            rec_digits = "".join(c for c in str(rec.get("phone", "")) if c.isdigit())
            if rec_digits and rec_digits[-10:] == digits[-10:]:
                cal = rec.get("calendar") or {}
                if cal.get("ok") and cal.get("event_id"):
                    return cal["event_id"]
    return None


def book_appointment(business_name: str, business_phone: str, service: str,
                     stylist: str, name: str, phone: str, date: str, time: str,
                     duration_min: int = 60, time_text: str = "", call_sid: str = "") -> dict:
    """Book a salon appointment: record it, add a calendar event (best
    effort), and text the caller an SMS appointment confirmation."""
    try:
        start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        start = None
    end = start + timedelta(minutes=duration_min) if start else None

    appt = {
        "type": "appointment", "business": business_name, "service": service,
        "stylist": stylist or "First available", "name": name, "phone": phone,
        "date": date, "time": time, "duration_min": duration_min,
        "time_text": time_text, "call_sid": call_sid,
    }
    _append("appointments.jsonl", appt)

    cal = {"ok": False, "error": "no date/time parsed"}
    if start and end:
        cal = _calendar_insert(
            summary=f"{service} — {name} ({stylist or 'First available'})",
            start=start, end=end,
            description=f"{business_name} appointment.\nService: {service}\nStylist: {stylist or 'First available'}\nCaller: {name}\nPhone: {phone}",
        )
        appt["calendar"] = cal

    when = f"{date} at {time}" if start else (time_text or "the time you chose")
    sms_body = (
        f"Hi {name}, your {service} at {business_name} is booked for {when}"
        + (f" with {stylist}" if stylist and stylist != "First available" else "")
        + f". Need to change it? Call {business_phone}."
    )
    sms = send_sms(phone, sms_body)
    appt["sms"] = sms
    _append("appointments.jsonl", {"type": "appointment_result", **appt})

    parts = [f"Booked a {service} for {name} on {when}."]
    parts.append("I texted them an SMS confirmation." if sms.get("ok")
                 else "I could not send the SMS confirmation, so please confirm by phone.")
    parts.append("It is on the calendar." if cal.get("ok")
                 else "The calendar is not connected yet, so the owner will confirm the time.")
    return {"ok": True, "message": " ".join(parts), "calendar": cal, "sms": sms}


def reschedule_appointment(business_name: str, business_phone: str, name: str,
                           phone: str, old_date: str, old_time: str,
                           new_date: str, new_time: str, duration_min: int = 60,
                           call_sid: str = "") -> dict:
    """Move an appointment: update the calendar event if one was recorded,
    log the change, and text the caller an SMS confirming the new time."""
    try:
        start = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        start = None
    end = start + timedelta(minutes=duration_min) if start else None

    event_id = _find_booking_event_id(phone, old_date, old_time)
    cal = {"ok": False, "error": "no earlier calendar event found"}
    if event_id and start and end:
        cal = _calendar_patch(event_id, start, end)
    elif start and end:
        cal = _calendar_insert(
            summary=f"Appointment — {name}",
            start=start, end=end,
            description=f"{business_name} appointment (rescheduled).\nCaller: {name}\nPhone: {phone}",
        )

    rec = {"type": "reschedule", "business": business_name, "name": name,
           "phone": phone, "old_date": old_date, "old_time": old_time,
           "new_date": new_date, "new_time": new_time, "call_sid": call_sid,
           "calendar": cal}
    _append("appointments.jsonl", rec)

    when = f"{new_date} at {new_time}" if start else f"{new_date} {new_time}"
    sms = send_sms(phone, f"Hi {name}, your appointment at {business_name} has been moved to {when}. Need to change it? Call {business_phone}.")
    rec["sms"] = sms
    _append("appointments.jsonl", {"type": "reschedule_result", **rec})

    parts = [f"Moved {name}'s appointment to {when}."]
    parts.append("I texted them an SMS confirming the new time." if sms.get("ok")
                 else "I could not send the SMS, so please confirm the new time by phone.")
    return {"ok": True, "message": " ".join(parts), "calendar": cal, "sms": sms}


def cancel_appointment(business_name: str, business_phone: str, name: str,
                       phone: str, date: str, time: str, call_sid: str = "") -> dict:
    """Cancel an appointment: remove the calendar event if one was recorded,
    log it, and text the caller an SMS confirming the cancellation."""
    event_id = _find_booking_event_id(phone, date, time)
    cal = {"ok": False, "error": "no calendar event found"}
    if event_id:
        cal = _calendar_delete(event_id)

    rec = {"type": "cancellation", "business": business_name, "name": name,
           "phone": phone, "date": date, "time": time, "call_sid": call_sid,
           "calendar": cal}
    _append("appointments.jsonl", rec)

    sms = send_sms(phone, f"Hi {name}, your appointment at {business_name} on {date} at {time} has been cancelled. To rebook, call {business_phone}.")
    rec["sms"] = sms
    _append("appointments.jsonl", {"type": "cancellation_result", **rec})

    parts = [f"Cancelled {name}'s appointment on {date} at {time}."]
    parts.append("I texted them an SMS confirming the cancellation." if sms.get("ok")
                 else "I could not send the SMS, so please confirm the cancellation by phone.")
    return {"ok": True, "message": " ".join(parts), "calendar": cal, "sms": sms}


def book_water_test(name: str, phone: str, address: str, date: str, time: str,
                    time_text: str = "", call_sid: str = "") -> dict:
    """Book a free water test: record it, add a calendar event (best effort),
    and text the caller an SMS appointment confirmation."""
    try:
        start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        start = None
    end = start + timedelta(hours=1) if start else None

    booking = {
        "type": "water_test",
        "name": name, "phone": phone, "address": address,
        "date": date, "time": time, "time_text": time_text,
        "call_sid": call_sid,
    }
    _append("bookings.jsonl", booking)

    cal = {"ok": False, "error": "no date/time parsed"}
    if start and end:
        cal = _calendar_insert(
            summary=f"Free water test — {name}",
            start=start, end=end,
            description=f"Osmora free water test.\nCaller: {name}\nPhone: {phone}\nAddress: {address}",
        )
        booking["calendar"] = cal

    # SMS appointment confirmation to the caller.
    when = f"{date} at {time}" if start else (time_text or "the time you chose")
    sms_body = (
        f"Hi {name}, your free water test with Osmora Water Solutions is booked "
        f"for {when} at {address}. No obligation. Need to change it? Call "
        f"{BUSINESS_PHONE}."
    )
    sms = send_sms(phone, sms_body)
    booking["sms"] = sms
    _append("bookings.jsonl", {"type": "water_test_result", **booking})

    parts = [f"Booked a free water test for {name} on {when}."]
    parts.append("I texted them an SMS confirmation." if sms.get("ok")
                 else "I could not send the SMS confirmation, so please confirm by phone.")
    parts.append("It is on the calendar." if cal.get("ok")
                 else "The calendar is not connected yet, so the owner will confirm the time.")
    return {"ok": True, "message": " ".join(parts), "calendar": cal, "sms": sms}


def take_message(name: str, phone: str, message: str, urgent: bool = False,
                 call_sid: str = "") -> dict:
    """Record a message for the owner."""
    _append("messages.jsonl", {
        "type": "message", "name": name, "phone": phone,
        "message": message, "urgent": urgent, "call_sid": call_sid,
    })
    if urgent:
        return {"ok": True,
                "message": f"Recorded an urgent message from {name}. The owner will call back right away."}
    return {"ok": True,
            "message": f"Recorded a message from {name}. The owner will call them back."}


def book_callback(name: str, phone: str, about: str, date: str = "",
                    time: str = "", time_text: str = "", call_sid: str = "") -> dict:
    """Book a callback or consultation: record it, add a calendar event
    (best effort), and text the caller an SMS confirmation."""
    start = None
    if date and time:
        try:
            start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except ValueError:
            start = None
    end = start + timedelta(minutes=30) if start else None

    cb = {
        "type": "callback", "name": name, "phone": phone, "about": about,
        "date": date, "time": time, "time_text": time_text, "call_sid": call_sid,
    }
    _append("callbacks.jsonl", cb)

    cal = {"ok": False, "error": "no date/time given"}
    if start and end:
        cal = _calendar_insert(
            summary=f"Callback — {name}",
            start=start, end=end,
            description=f"Web services callback.\nCaller: {name}\nPhone: {phone}\nAbout: {about}",
        )
        cb["calendar"] = cal

    when = f"{date} at {time}" if start else (time_text or "as soon as possible")
    sms_body = (
        f"Hi {name}, your callback is booked for {when} about: {about}. "
        f"Need to change it? Call {BUSINESS_PHONE}."
    )
    sms = send_sms(phone, sms_body)
    cb["sms"] = sms
    _append("callbacks.jsonl", {"type": "callback_result", **cb})

    parts = [f"Booked a callback for {name} for {when}."]
    parts.append("I texted them an SMS confirmation." if sms.get("ok")
                 else "I could not send the SMS confirmation, so please confirm by phone.")
    parts.append("It is on the calendar." if cal.get("ok")
                 else "The calendar is not connected yet, so the owner will confirm the time.")
    return {"ok": True, "message": " ".join(parts), "calendar": cal, "sms": sms}


def transfer_to_owner(call_sid: str, kind: str = "general") -> dict:
    """Transfer the live call to the owner (OWNER_PHONE). The owner hears a
    short whisper first — e.g. 'Water services call.' — so they know what
    kind of call it is before they are connected to the caller.

    How it works: Twilio redirects the in-progress call (via the REST API)
    to the server's /transfer endpoint, which dials the owner. The dial uses
    a <Number url> pointing at /whisper, and Twilio plays that TwiML to the
    owner as a whisper the moment they pick up, then bridges the caller.
    kind is 'water', 'it', or 'general' (salons / anything else).
    """
    kind = (kind or "general").strip().lower()
    if kind not in ("web", "water", "it", "general"):
        kind = "general"
    if not (TWILIO_SID and TWILIO_TOKEN):
        return {"ok": False, "message": "Twilio credentials are not configured, so I cannot transfer the call."}
    if not OWNER_PHONE:
        return {"ok": False, "message": "The owner's number is not set, so I cannot transfer the call."}
    if not PUBLIC_BASE_URL:
        return {"ok": False, "message": "The server has no public URL yet, so I cannot transfer the call."}
    if not call_sid:
        return {"ok": False, "message": "I could not identify this call, so I cannot transfer it."}
    transfer_url = f"{PUBLIC_BASE_URL}/transfer?kind={kind}"
    try:
        _twilio().calls(call_sid).update(url=transfer_url, method="POST")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"The transfer failed: {e}"}
    _append("transfers.jsonl", {
        "type": "transfer", "call_sid": call_sid, "kind": kind,
        "to": OWNER_PHONE, "transfer_url": transfer_url,
    })
    label = {"web": "Web services", "water": "Water services",
             "it": "IT services"}.get(kind, "Osmora")
    return {"ok": True,
            "message": f"Transferring the call to the owner now. They will hear '{label} call' before being connected."}


def write_call_summary(call_sid: str, caller: str, started_at: str,
                       transcript: list, tools_used: list) -> dict:
    """Append the call record and, if OWNER_PHONE is set, text the owner a
    short summary. Returns the record."""
    summary_lines = [f"Osmora call from {caller}."]
    for t in tools_used:
        summary_lines.append(f"- {t}")
    if not tools_used:
        summary_lines.append("- No booking or message taken.")
    summary = "\n".join(summary_lines)
    record = {
        "call_sid": call_sid, "caller": caller, "started_at": started_at,
        "ended_at": datetime.now(TZ).isoformat(),
        "tools_used": tools_used, "transcript": transcript, "summary": summary,
    }
    _append("calls.jsonl", record)
    sms = {"ok": False, "error": "OWNER_PHONE not set"}
    if OWNER_PHONE:
        sms = send_sms(OWNER_PHONE, summary)
    record["owner_sms"] = sms
    return record
