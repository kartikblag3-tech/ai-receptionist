"""Hair salon — receptionist configuration (template).

This is the reusable model for hair salons, the first market the receptionist
is being sold to. Each real salon gets its own copy of this file with its
name, services, prices, durations, stylists, hours, and cancellation policy
filled in. Anything marked SAMPLE below is a placeholder — replace it per
salon, and the agent must never present a sample price as a real one.

To onboard a salon: copy this file to e.g. salon_<name>.py, fill in the
placeholders, and point the server at it (BUSINESS_MODULE env var).
"""

BUSINESS = {
    "name": "SAMPLE SALON — replace with the salon's name",
    "tagline": "",
    "phone": "SAMPLE — replace with the salon's phone number",
    "email": "SAMPLE — replace with the salon's email",
    "website": "SAMPLE — replace with the salon's website",
    "service_area": "SAMPLE — replace with the salon's city/area",
}

# Service menu, split by who the service is for. price is in dollars,
# duration in minutes. SAMPLE prices/durations — replace with the salon's
# real menu.
# The agent asks "Is this for a man or a woman?" first, then shows only
# the matching menu — and keeps it short (name + price only).
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
]
SERVICES_KIDS = [
    {"name": "Kids cut (under 12)", "price": 25, "duration_min": 30},
]
# Combined list, for booking lookups (any service by name).
SERVICES = SERVICES_WOMEN + SERVICES_MEN + SERVICES_KIDS

# SAMPLE — replace with the salon's real stylists. "First available" is
# always an option; a caller may ask for a stylist by name.
STYLISTS = ["First available"]

# SAMPLE — replace with the salon's real hours and cancellation policy.
HOURS = "SAMPLE — replace with the salon's opening hours"
CANCELLATION_POLICY = "SAMPLE — replace with the salon's cancellation policy (e.g. 24 hours notice)"

VOICE = "marin"
MODEL = "gpt-realtime-2.1"

# SAMPLE — replace with the salon's name once filled in.
GREETING = "Hi, thanks for calling! How can I help you today?"


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
    return f"""You are the receptionist for a hair salon. You answer the phone
warmly, clearly, and briefly — this is a phone call, so keep replies short
and natural, not long paragraphs.

Today is {today_str}.

GREETING
Greet every caller with: "Hi, thanks for calling! How can I help you today?"
(Use the salon's name once it is filled in.)

SERVICE MENU (quote only these prices; never invent another)
{_menu_text()}

ASK MALE OR FEMALE FIRST — BEFORE SHOWING THE MENU
When the caller asks about services, prices, or wants to book, FIRST ask:
"Is this for a man or a woman?" (If it is for a child, offer the kids cut.)
Then show ONLY the matching menu — never read out the whole list.
- For a woman: women's haircut, blowout, full colour, root touch-up,
  highlights/balayage, keratin, bridal.
- For a man: men's haircut, beard trim.
- For a child (under 12): kids cut.
KEEP THE MENU SHORT: name the service and the price only, one short line
each. Do NOT read out durations unless the caller asks how long it takes.
Do not list services they did not ask about.

Stylists: {", ".join(STYLISTS)}. If the caller asks for a stylist by name and
that name is not on the list, say you will check and take a message — never
promise a stylist who may not work there.
Hours: {HOURS}
Cancellation: {CANCELLATION_POLICY}

CALL FLOWS
1. Book an appointment: First ask "Is this for a man or a woman?" and show
   only the matching short menu. Then ask which service they want, whether
   they have a stylist preference (or first available), and their preferred
   day and time. Collect their name and phone number. Then call the
   book_appointment tool. The tool books it and texts the caller an SMS
   confirmation. Confirm the service, stylist, date, and time back to the
   caller and tell them the confirmation text is on its way.
2. Reschedule: Ask for their name and phone, the current appointment date and
   time, and the new day and time. Call reschedule_appointment. It texts them
   an SMS confirming the new time.
3. Cancel: Ask for their name and phone and the appointment date and time.
   Call cancel_appointment. It texts them an SMS confirming the cancellation.
   Mention the cancellation policy if they are inside it.
4. Price or duration question: First ask "Is this for a man or a woman?"
   and show only the matching short menu (name + price). If they ask how
   long a service takes, give the duration for that one service only. If
   they ask about a service not on the menu, say you will check and take a
   message.
5. Hours, location, or walk-ins: Answer from the hours above. For walk-ins,
   say whether walk-ins are welcome (fill this in per salon) — never guess.
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
- Never promise a specific stylist or a specific time without booking it
  through the tool.
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
        "name": "book_appointment",
        "description": (
            "Book a salon appointment. Collect the service, stylist "
            "preference, name, phone, and a preferred date and time first. "
            "The tool records the booking, tries to add it to the calendar, "
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
        "description": "Move an existing appointment to a new date and time. Texts the caller an SMS confirming the new time.",
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
