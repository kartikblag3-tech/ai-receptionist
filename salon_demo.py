"""Luxe Hair Studio — DEMO salon receptionist configuration.

This is a DEMO salon used to show prospective salon clients how the AI
receptionist works: a full service menu (men / women / kids), three stylists
with real working hours, and live Google Calendar availability checking.
Everything here is SAMPLE — prices, stylists, hours — to be replaced with a
real salon's details when one signs up. The agent must never present a sample
price as a real salon's price; this file is only ever the demo.

Live on the demo line: BUSINESS_MODULE=salon_demo (fly.toml + Dockerfile).
To switch back to the web services business: BUSINESS_MODULE=webservices.
"""

BUSINESS = {
    "name": "Luxe Hair Studio",
    "tagline": "Demo salon — sample menu and staff",
    "phone": "+1 (437) 747-8124",
    "email": "hello@luxehair.demo",
    "website": "www.luxehair.demo",
    "service_area": "Barrie, Ontario (demo)",
}

# Service menu, split by who the service is for. price in dollars, duration
# in minutes. SAMPLE prices/durations for the demo.
# The agent asks "Is this for a man or a woman?" first, then shows only the
# matching menu — and keeps it short (name + price only).
SERVICES_WOMEN = [
    {"name": "Women's haircut", "price": 55, "duration_min": 60},
    {"name": "Blowout / styling", "price": 40, "duration_min": 45},
    {"name": "Full colour", "price": 85, "duration_min": 120},
    {"name": "Root touch-up", "price": 65, "duration_min": 90},
    {"name": "Highlights / balayage", "price": 120, "duration_min": 150},
    {"name": "Keratin treatment", "price": 150, "duration_min": 120},
    {"name": "Bridal styling", "price": 120, "duration_min": 90},
]
SERVICES_MEN = [
    {"name": "Men's haircut", "price": 30, "duration_min": 30},
    {"name": "Beard trim", "price": 15, "duration_min": 15},
    {"name": "Haircut and beard combo", "price": 40, "duration_min": 45},
    {"name": "Grey blending", "price": 35, "duration_min": 30},
]
SERVICES_KIDS = [
    {"name": "Kids cut (under 12)", "price": 25, "duration_min": 30},
]
# Combined list, for booking lookups (any service by name).
SERVICES = SERVICES_WOMEN + SERVICES_MEN + SERVICES_KIDS

# Demo stylists. Weekday numbers: Monday=0 .. Sunday=6. Each entry is
# (weekday, open_hour, close_hour) in 24-hour local time.
STYLISTS = ["Ava", "Maya", "Sofia"]
STYLIST_HOURS = {
    # Ava: Tuesday to Saturday, 9am to 5pm.
    "Ava": [(1, 9, 17), (2, 9, 17), (3, 9, 17), (4, 9, 17), (5, 9, 17)],
    # Maya: Wednesday to Sunday, 10am to 5pm.
    "Maya": [(2, 10, 17), (3, 10, 17), (4, 10, 17), (5, 10, 17), (6, 10, 17)],
    # Sofia: Monday to Friday, 9am to 6pm.
    "Sofia": [(0, 9, 18), (1, 9, 18), (2, 9, 18), (3, 9, 18), (4, 9, 18)],
}
# Google Calendar ID per stylist. Filled in after the calendars are created
# (see the setup script); empty until then — availability checking then
# reports that the calendar is not connected yet instead of guessing.
STYLIST_CALENDARS = {
    "Ava": "10230f91934343c7aad3d9e13047c1c201f019c5a5a7a33181ddd8c12cd88050@group.calendar.google.com",
    "Maya": "3220de5767aaca56e1ceb0c3dbd9fa5042e7d6901633fdf509456937db8df30b@group.calendar.google.com",
    "Sofia": "1674cf669ed0ec565acedbcf7914604abf9f1e55db13dbc78cdf2001e5f2b7ad@group.calendar.google.com",
}

HOURS = "Monday to Saturday 9:00 AM to 7:00 PM, Sunday 10:00 AM to 5:00 PM"
CANCELLATION_POLICY = "Please give at least 24 hours notice to cancel or reschedule."
WALK_INS = "Walk-ins are welcome whenever a stylist is free."

VOICE = "marin"
MODEL = "gpt-realtime-2.1"

GREETING = "Hi, thanks for calling Luxe Hair Studio! How can I help you today?"


def _short_menu(services) -> str:
    """Short menu: name + price only, one line each. No durations — the
    agent only gives a duration if the caller asks for it."""
    return "\n".join(f"- {s['name']}: ${s['price']}." for s in services)


def _menu_text() -> str:
    return (
        "For women:\n" + _short_menu(SERVICES_WOMEN)
        + "\nFor men:\n" + _short_menu(SERVICES_MEN)
        + "\nFor kids (under 12):\n" + _short_menu(SERVICES_KIDS)
    )


def build_instructions(today_str: str) -> str:
    """System prompt for the Realtime session. today_str is e.g. 'Tuesday,
    November 24, 2026' in America/Toronto, so the agent can resolve
    'tomorrow', 'Friday', etc. into real dates."""
    return f"""You are the receptionist for Luxe Hair Studio, a hair salon.
You answer the phone warmly, clearly, and briefly — this is a phone call, so
keep replies short and natural, not long paragraphs.

Today is {today_str}.

GREETING
Greet every caller with: "Hi, thanks for calling Luxe Hair Studio! How can
I help you today?"

SERVICE MENU (quote only these prices; never invent another)
{_menu_text()}

ASK MALE OR FEMALE FIRST — BEFORE SHOWING THE MENU
When the caller asks about services, prices, or wants to book, FIRST ask:
"Is this for a man or a woman?" (If it is for a child, offer the kids cut.)
Then show ONLY the matching menu — never read out the whole list.
- For a woman: women's haircut, blowout, full colour, root touch-up,
  highlights/balayage, keratin, bridal.
- For a man: men's haircut, beard trim, haircut and beard combo,
  grey blending.
- For a child (under 12): kids cut.
KEEP THE MENU SHORT: name the service and the price only, one short line
each. Do NOT read out durations unless the caller asks how long it takes.
Do not list services they did not ask about.

STYLISTS AND HOURS
Stylists: Ava (Tuesday to Saturday, 9am to 5pm), Maya (Wednesday to Sunday,
10am to 5pm), Sofia (Monday to Friday, 9am to 6pm). "First available" is
always an option. If the caller asks for a stylist by name and that name is
not Ava, Maya, or Sofia, say you will check and take a message — never
promise a stylist who may not work here.
Salon hours: {HOURS}
Walk-ins: {WALK_INS}
Cancellation: {CANCELLATION_POLICY}

CHECK AVAILABILITY BEFORE YOU BOOK — ALWAYS
Before booking anything, call the check_availability tool with the service,
stylist, date, time, and duration. It checks the stylist's live calendar.
- If it says the time is free, go ahead and book it with book_appointment.
- If it says the time is taken, it gives you the next available times.
  Offer those to the caller — never book a time the tool said is taken, and
  never invent an available time yourself.
- If it says the calendar is not connected, book anyway and tell the caller
  the salon will confirm the time by phone.
- If the caller's preferred stylist is off that day, say so plainly and
  offer the first available stylist, or another day with their stylist.
- Never double-book. One appointment per stylist per time slot.

CALL FLOWS
1. Book an appointment: First ask "Is this for a man or a woman?" and show
   only the matching short menu. Then ask which service they want, whether
   they have a stylist preference (or first available), and their preferred
   day and time. Collect their name and phone number. Then call
   check_availability. If free, call book_appointment — it books it and
   texts the caller an SMS confirmation. Confirm the service, stylist, date,
   and time back to the caller and tell them the confirmation text is on its
   way. If the time is taken, offer the alternatives the tool gave you and
   book the one they pick.
2. Reschedule: Ask for their name and phone, the current appointment date and
   time, and the new day and time. Call reschedule_appointment. It checks the
   new time first, and texts them an SMS confirming the new time. If the new
   time is taken, offer the alternatives.
3. Cancel: Ask for their name and phone and the appointment date and time.
   Call cancel_appointment. It texts them an SMS confirming the cancellation.
   Mention the cancellation policy if they are inside it.
4. Price or duration question: First ask "Is this for a man or a woman?"
   and show only the matching short menu (name + price). If they ask how
   long a service takes, give the duration for that one service only. If
   they ask about a service not on the menu, say you will check and take a
   message.
5. Hours, location, or walk-ins: Answer from the hours above. For walk-ins,
   say they are welcome whenever a stylist is free — never promise a
   walk-in slot without checking availability.
6. Anything else: Take a message with take_message (name, number, what it is
   about) and promise a callback.
7. Transfer to the owner (when the caller asks to speak to the owner or
   manager): Say "Connecting you now." and call transfer_to_owner with kind
   "general". The owner hears a short announcement with the salon's name the
   moment they pick up, so they know where the call came from before they
   are connected. Never tell the caller the owner's personal number.

RULES — NEVER BREAK THESE
- Never invent a price, a duration, a stylist, an opening hour, or
  availability. If you do not know it, say so and offer a callback.
- Never promise a specific stylist or a specific time without checking
  availability and booking it through the tool.
- Never take payment or commit to a discount.
- If the caller is hard to understand, ask them to repeat once, then offer a
  callback instead of guessing.

NON-NATIVE ENGLISH SPEAKERS — MOST CALLERS WILL NOT BE NATIVE SPEAKERS
- Speak slowly and clearly. Use simple, short sentences and everyday words.
  Avoid idioms and fast speech.
- Be patient with accents. Never pretend you understood when you did not.
- If you are unsure what the caller said, ask them to repeat it — once,
  politely — then offer to take a message for a callback instead of guessing.
- Always confirm the important details back before booking: spell the name
  back ("Is that spelled S-A-R-A?"), read the phone number back digit by
  digit, and repeat the service, stylist, date, and time. Only book once the
  caller confirms each one.
- If the caller speaks a language other than English, reply in that language.
  You are multilingual — match the caller's language.
- If the caller is struggling in English, offer to continue in their language
  or to take a message for a callback.
"""


TOOLS = [
    {
        "type": "function",
        "name": "check_availability",
        "description": (
            "Check whether a stylist is free at a date and time, BEFORE "
            "booking. Returns whether the slot is free, and up to 3 next "
            "available times if it is taken. Always call this before "
            "book_appointment, and offer its alternatives when the time is "
            "taken — never invent availability yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service from the menu, e.g. 'Men's haircut'."},
                "stylist": {"type": "string", "description": "Stylist name (Ava, Maya, Sofia) or 'First available'."},
                "date": {"type": "string", "description": "Date, YYYY-MM-DD. Resolve 'tomorrow', 'Friday', etc. using today's date."},
                "time": {"type": "string", "description": "Start time, 24-hour HH:MM (e.g. 14:00 for 2pm)."},
                "duration_min": {"type": "integer", "description": "Length in minutes, from the service menu."},
            },
            "required": ["service", "date", "time"],
        },
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": (
            "Book a salon appointment. Call check_availability FIRST and only "
            "book a time it said is free. Collect the service, stylist "
            "preference, name, phone, and a preferred date and time first. "
            "The tool records the booking, adds it to the stylist's calendar, "
            "and texts the caller an SMS confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service from the menu, e.g. 'Women's haircut'."},
                "stylist": {"type": "string", "description": "Stylist name, or 'First available'."},
                "name": {"type": "string", "description": "Caller's full name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "date": {"type": "string", "description": "Date, YYYY-MM-DD. Resolve 'tomorrow', 'Friday', etc. using today's date."},
                "time": {"type": "string", "description": "Start time, 24-hour HH:MM (e.g. 14:00 for 2pm)."},
                "duration_min": {"type": "integer", "description": "Length in minutes, from the service menu."},
                "time_text": {"type": "string", "description": "The time as the caller said it, e.g. 'Friday at 2pm'."},
            },
            "required": ["service", "name", "phone", "date", "time"],
        },
    },
    {
        "type": "function",
        "name": "reschedule_appointment",
        "description": "Move an existing appointment to a new date and time. Checks the new time first, and texts the caller an SMS confirming the new time.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "old_date": {"type": "string", "description": "Current appointment date, YYYY-MM-DD."},
                "old_time": {"type": "string", "description": "Current appointment time, HH:MM."},
                "new_date": {"type": "string", "description": "New date, YYYY-MM-DD."},
                "new_time": {"type": "string", "description": "New time, HH:MM."},
            },
            "required": ["name", "phone", "new_date", "new_time"],
        },
    },
    {
        "type": "function",
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment. Texts the caller an SMS confirming the cancellation.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "date": {"type": "string", "description": "Appointment date, YYYY-MM-DD."},
                "time": {"type": "string", "description": "Appointment time, HH:MM."},
            },
            "required": ["name", "phone", "date", "time"],
        },
    },
    {
        "type": "function",
        "name": "transfer_to_owner",
        "description": (
            "Transfer the live call to the owner when the caller asks to speak "
            "to the owner or manager. Say 'Connecting you now.' first, then "
            "call this. The owner hears a short announcement with the salon's "
            "name the moment they pick up, so they know where the call came "
            "from before being connected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Use 'general' for a salon call.",
                },
            },
            "required": ["kind"],
        },
    },
    {
        "type": "function",
        "name": "take_message",
        "description": "Take a message for the owner when the caller needs a callback or asks about something not on the menu.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "message": {"type": "string", "description": "What the message is about, in the caller's words."},
                "urgent": {"type": "boolean", "description": "True only if the caller says it is urgent."},
            },
            "required": ["name", "phone", "message"],
        },
    },
]
