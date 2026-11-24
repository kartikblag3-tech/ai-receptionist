"""Web services — receptionist configuration.

This is the ONLY business the receptionist answers for. Osmora Water
Solutions is NOT involved in the receptionist at all (user, 2026-11-24).
The receptionist answers only on the Twilio number +1 (437) 747-8124.

The business name and the exact services list are not filled in yet — the
user has not given them. Anything marked TODO is a placeholder. The agent
must never invent a service, a price, or a business hour. Until the user
fills these in, the agent answers generally, takes messages, books callbacks,
and transfers to the owner.
"""

BUSINESS = {
    # TODO: user to provide the web services business name.
    "name": "Web Services",
    "tagline": "",
    # The receptionist answers ONLY on this Twilio number.
    "phone": "+1 (437) 747-8124",
    # TODO: user to provide email and website.
    "email": "",
    "website": "",
    "service_area": "",
}

# TODO: user to provide the web services offered (and prices, if the agent
# should quote them). Until then the agent does not list or quote services.
SERVICES = []

VOICE = "marin"  # OpenAI Realtime voice. Alternatives: cedar, alloy, shimmer.
MODEL = "gpt-realtime-2.1"

GREETING = "Hi, thanks for calling. How can I help you today?"


def build_instructions(today_str: str) -> str:
    """System prompt for the Realtime session. today_str is e.g. 'Tuesday,
    November 24, 2026' in America/Toronto, so the agent can resolve
    'tomorrow', 'Friday', etc. into real dates."""
    return f"""You are the receptionist for a web services business. You answer
the phone warmly, clearly, and briefly — this is a phone call, so keep replies
short and natural, not long paragraphs.

Today is {today_str}.

GREETING
Greet every caller with: "Hi, thanks for calling. How can I help you today?"

WHAT THIS BUSINESS DOES
- Web services. The exact services list has not been given to you yet, so do
  not list services, quote prices, or state hours. If the caller asks what
  services are offered or what something costs, say you will check and take a
  message for a callback, or offer to connect them to the owner.
- Contact: phone +1 (437) 747-8124. This is the only number for this
  receptionist.

CALL FLOWS
1. General question about web services: Listen to what they need. If you
   know the answer, answer it briefly. If you do not know it, say you will
   check and offer to take a message or connect them to the owner.
2. Book a callback or consultation: Collect the caller's name, phone number,
   what it is about, and a preferred day and time (or "as soon as possible").
   Then call the book_callback tool. The tool records it and texts the caller
   an SMS confirmation. Confirm the details back to the caller.
3. Transfer to the owner (when the caller asks to speak to a person, or a
   question needs the owner): Say "Connecting you now." and call
   transfer_to_owner with kind "web". The owner hears a short announcement
   first — "Web services call." — so they know where the call came from
   before they are connected. Never tell the caller the owner's personal
   number.
4. Anything else: Take a message with take_message (name, number, what it is
   about) and promise a callback.

RULES — NEVER BREAK THESE
- Never invent a service, a price, a business hour, or availability. If you
  do not know it, say so and offer a callback or a transfer to the owner.
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
  digit, and repeat the date, time, and what it is about. Only book once the
  caller confirms each one.
- If the caller speaks a language other than English, reply in that language.
  You are multilingual — match the caller's language.
- If the caller is struggling in English, offer to continue in their language
  or to take a message for a callback.
"""


# Tools the model can call. The server implements these in tools.py.
TOOLS = [
    {
        "type": "function",
        "name": "book_callback",
        "description": (
            "Book a callback or consultation for a caller. Collect name, "
            "phone, what it is about, and a preferred date and time first. "
            "The tool records the callback and texts the caller an SMS "
            "confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's full name."},
                "phone": {
                    "type": "string",
                    "description": "Caller's phone number, digits only if possible.",
                },
                "about": {
                    "type": "string",
                    "description": "What the callback is about, in the caller's words.",
                },
                "date": {
                    "type": "string",
                    "description": "Preferred date, YYYY-MM-DD. Resolve 'tomorrow', 'Friday', etc. using today's date. Use an empty string if they said 'as soon as possible'.",
                },
                "time": {
                    "type": "string",
                    "description": "Preferred start time, 24-hour HH:MM (e.g. 14:00 for 2pm). Use an empty string if they said 'as soon as possible'.",
                },
                "time_text": {
                    "type": "string",
                    "description": "The time as the caller said it, e.g. 'tomorrow at 2pm' or 'as soon as possible'.",
                },
            },
            "required": ["name", "phone", "about"],
        },
    },
    {
        "type": "function",
        "name": "transfer_to_owner",
        "description": (
            "Transfer the live call to the owner when the caller asks to speak "
            "to a person, or a question needs the owner. Say 'Connecting you "
            "now.' first, then call this. The owner hears a short announcement "
            "— 'Web services call.' — the moment they pick up, so they know "
            "where the call came from before being connected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Use 'web' for a web services call.",
                },
            },
            "required": ["kind"],
        },
    },
    {
        "type": "function",
        "name": "take_message",
        "description": (
            "Take a message for the owner when the caller needs a callback or "
            "asks about something the agent cannot answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Caller's name."},
                "phone": {"type": "string", "description": "Caller's phone number."},
                "message": {
                    "type": "string",
                    "description": "What the message is about, in the caller's words.",
                },
                "urgent": {
                    "type": "boolean",
                    "description": "True only if the caller says it is urgent.",
                },
            },
            "required": ["name", "phone", "message"],
        },
    },
]
