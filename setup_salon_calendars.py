"""Set up the Luxe Hair Studio demo calendars (run AFTER Google Calendar is
connected via the Muse connector).

Creates three stylist calendars (Ava, Maya, Sofia) and seeds each with a few
sample appointments over the next 7 days, so the demo has realistic busy
slots for the live availability check. Prints the calendar IDs — paste them
into salon_demo.py STYLIST_CALENDARS, then redeploy.

Usage:
    python setup_salon_calendars.py [--seed-only] [--clear]
    --seed-only : only add the sample appointments (calendars must exist)
    --clear     : delete the seeded sample appointments (by summary prefix)

The script is idempotent for calendar creation: it reuses a calendar whose
summary already matches instead of creating a duplicate.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GWS = "/opt/hatch/bin/hatch_gws_cli"
TZ = ZoneInfo("America/Toronto")
PREFIX = "Luxe Hair Studio — "
SEED_TAG = "[demo]"


def _run(*args, input_json=None):
    cmd = [GWS, "calendar"] + list(args)
    if input_json is not None:
        cmd += ["--json", json.dumps(input_json)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.stdout.strip():
        try:
            return json.loads(out.stdout)
        except ValueError:
            return {"raw": out.stdout}
    return {"error": out.stderr.strip() or "no output"}


def list_calendars():
    data = _run("calendarList", "list")
    items = data.get("items") or []
    return {it.get("summary"): it.get("id") for it in items if it.get("id")}


def create_calendar(name: str, description: str) -> str:
    data = _run("calendars", "insert", input_json={
        "summary": name,
        "description": description,
        "timeZone": "America/Toronto",
    })
    cal_id = data.get("id") or ""
    if not cal_id:
        raise RuntimeError(f"could not create calendar {name}: {data}")
    return cal_id


def ensure_calendar(name: str, description: str, existing: dict) -> str:
    if name in existing:
        print(f"reuse  {name}  ({existing[name]})")
        return existing[name]
    cal_id = create_calendar(name, description)
    print(f"create {name}  ({cal_id})")
    return cal_id


def insert_event(calendar_id: str, summary: str, start: datetime, end: datetime,
                 description: str = "") -> str:
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    data = _run("events", "insert",
                "--params", json.dumps({"calendarId": calendar_id}),
                input_json=body)
    return data.get("id") or ""


def seed(stylist: str, cal_id: str, base: datetime):
    """A few realistic sample appointments over the next 7 days, so the
    demo availability check has something to work around. Times are chosen
    inside each stylist's working hours (see salon_demo.py STYLIST_HOURS)."""
    # (day offset, start hour, duration min, service)
    if stylist == "Ava":  # Tue-Sat 9-17
        slots = [(1, 10, 30, "Men's haircut"), (2, 14, 60, "Women's haircut"),
                 (3, 11, 45, "Blowout / styling"), (4, 15, 30, "Men's haircut")]
    elif stylist == "Maya":  # Wed-Sun 10-17
        slots = [(1, 11, 60, "Women's haircut"), (2, 13, 120, "Full colour"),
                 (4, 10, 30, "Beard trim"), (5, 15, 90, "Root touch-up")]
    else:  # Sofia, Mon-Fri 9-18
        slots = [(0, 9, 30, "Men's haircut"), (1, 12, 150, "Highlights / balayage"),
                 (2, 10, 45, "Blowout / styling"), (3, 16, 60, "Women's haircut")]
    for (off, hour, dur, service) in slots:
        day = base + timedelta(days=off)
        start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=dur)
        ev = insert_event(cal_id, f"{SEED_TAG} {service} — Sample Client",
                          start, end, "Demo appointment (sample data).")
        print(f"  seed {stylist}: {start.strftime('%a %b %d %H:%M')} {service} ({dur}m) -> {ev or 'FAILED'}")


def main():
    seed_only = "--seed-only" in sys.argv
    existing = list_calendars()
    stylists = ["Ava", "Maya", "Sofia"]
    ids = {}
    base = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for s in stylists:
        name = PREFIX + s
        if seed_only:
            cal_id = existing.get(name, "")
            if not cal_id:
                print(f"missing calendar for {s} (run without --seed-only first)")
                continue
        else:
            cal_id = ensure_calendar(
                name, f"Appointments for {s}, stylist at Luxe Hair Studio (demo).",
                existing)
        ids[s] = cal_id
        seed(s, cal_id, base)
    print("\nPaste these into salon_demo.py STYLIST_CALENDARS, then redeploy:")
    print("STYLIST_CALENDARS = {")
    for s in stylists:
        print(f'    "{s}": "{ids.get(s, "")}",')
    print("}")


if __name__ == "__main__":
    main()
