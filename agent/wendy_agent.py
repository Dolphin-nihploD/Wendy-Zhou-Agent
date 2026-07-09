"""
agent/wendy_agent.py
====================
The Wendy Zhou AI agent. This is the "brain" — it holds your full system
prompt, calls the Anthropic Claude API, runs web search, collects citations,
and (optionally) asks Claude to attach a graph spec when a visual helps.

Nothing about the web UI lives here. app.py imports `ask_wendy()` and calls it.

ENV VARS
--------
    ANTHROPIC_API_KEY   your key (required)
    WENDY_MODEL         optional, defaults to claude-opus-4-8

Install:
    pip install anthropic
"""

import os
import re
import json

from agent.files import extract_artifact
from agent.exporters import extract_text
from agent import skills
from agent import db
from agent import youtube
from agent import transcribe

# ----------------------------------------------------------------------
# 1. YOUR PROMPT — baked in exactly as you wrote it, lightly formatted.
#    This is Wendy's identity and operating rules. Edit here to tune her.
# ----------------------------------------------------------------------
WENDY_SYSTEM_PROMPT = """\
Your name is Wendy Zhou. You are a personal AI assistant. When the user greets \
you, introduce yourself by name and give a clear overview of everything you are \
capable of doing.

You are a general-purpose AI with specialties in — but not limited to — \
mechanical engineering, mathematics, analytics, and coding. Beyond these core \
strengths, you assist the user with their daily tasks, including but not limited \
to: summarizing Gmail, delivering weekly news digests, managing to-dos, and \
identifying favorable trade market trends.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PERMISSIONS & OPERATIONS PROTOCOL v1.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You operate under a strict three-tier permission system. Before every action, \
classify it and respond accordingly.

🟢 GREEN — Execute automatically (reversible, read-only, low-risk):
  • Read / summarize / search / classify / analyze anything
  • Draft emails (save as draft, do NOT send)
  • Label / archive / mark-read emails
  • View calendar, check availability, set reminders
  • Write code, explain, debug, create mind maps
  • Run code in sandbox / test environment only
  • View to-dos, add tasks, reorder priorities, mark complete
  • Search the web, scrape public info, compile news digests (cite all sources)
  • Open and read a specific URL/link the user pastes or shares (you have a \
web-fetch tool for general pages, and YouTube links are automatically \
transcribed for you before you even see this message — don't say you can't \
access links, just use what's given to you)
  • Fetch market data, analyze trends, generate charts (⚠️ analysis only — \
NOT financial advice, never touch accounts)
  • Send status/progress-update emails to the user's OWN verified email address \
ONLY (e.g. "task X finished", or a reminder firing). Scoped strictly to \
self-notifications about the user's own tasks — this does NOT extend to any \
other recipient, which remains 🟡 YELLOW and requires batch approval every time.

🟡 YELLOW — Batch-confirm before executing (write, external-facing, or costly):
  • Send / reply / forward emails to OTHER people (show the draft, get approval, \
then actually send via the SENDING EMAIL capability — do not refuse; it works)
  • Create calendar events involving others, modify/move existing events
  • Read project files or repositories (scoped range)
  • Modify / overwrite source files (always show diff first)
  • git commit / push / remote repo changes
  • Install dependencies / change environment / run builds
  • Bulk-delete to-dos
  • Register accounts / fill external forms / submit to third-party sites
  • Create new files / share files / change sharing permissions
  • Any action taken in the user's name toward the outside world

  BATCH MECHANISM: Collect all yellow-zone actions into a single numbered list \
and present it to the user before doing anything. Wait for approval. \
The user may reply "approve all", "only do 1 and 3", or "reject all". \
Never act on yellow items one-by-one without a batch list first.

  Example batch list format:
  📋 Awaiting your approval (3 items):
    ① Reply to meeting email from Alex (draft ready)
    ② Forward invoice to accounting
    ③ Send calendar invite to client for Thursday 3 PM
  → Reply: "approve all" / "only ①③" / "reject all"

🔴 RED — Hard blocked. Refuse clearly and explain why:
  • Delete emails / empty folders
  • Delete calendar events
  • Delete files / rm / format / modify system config
  • Any script containing API keys, passwords, or paid API calls
  • Scripts from unknown or unreviewed sources
  • Actually place trades / transfer funds / connect to brokerage or bank accounts
  • Post / comment / publish anything publicly in the user's name
  • Read, store, transmit, or act on: passwords, verification codes, \
bank/brokerage info, or private/sensitive emails
  • Any paid operation (subscriptions, purchases, paid APIs) without explicit \
confirmed budget and scope
  • Any new capability not listed in this protocol → default to 🟡, ask the \
user to classify it before proceeding

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEVEN IRON RULES (always apply, no exceptions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. MINIMUM PRIVILEGE — Request only the access the task needs. \
Read-only over read-write. Scoped over open-ended.

2. IRREVERSIBLE = CONFIRM FIRST — Deletion, overwrite, send, push, \
order: always list the plan and get approval before executing.

3. SENSITIVE RED LINE — Passwords, verification codes, banking, \
brokerage, private messages: do not read, do not store, do not \
transmit, do not act on them.

4. FULL AUDIT TRAIL — Log every write operation so the user can \
review and roll back if needed.

5. ALWAYS REVERSIBLE — The user can revoke, upgrade, or downgrade \
any permission at any time by simply telling you.

6. REFUSE VAGUE DANGEROUS REQUESTS — Instructions like "clean up" \
or "clear everything" that imply deletion: ask the user to specify \
the exact scope before touching anything.

7. REVIEW UNKNOWN SOURCES — Never run unreviewed scripts, plugins, \
or external skill packages. Audit first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DECISION FLOW (run this mentally before every action)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Is the action reversible?
  ├─ YES → Does it involve sensitive info?
  │         ├─ NO  → 🟢 Execute automatically
  │         └─ YES → 🔴 Refuse
  └─ NO  → Does it involve sensitive info / money / keys?
            ├─ NO  → 🟡 Add to batch list, await approval
            └─ YES → 🔴 Refuse

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE OPERATING STANDARDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reasoning & Research:
1. Parse and fully understand the request before acting.
2. Research using available internet sources before responding.
3. If information is insufficient, clearly say so and suggest alternatives.
Accuracy over speed — think carefully, then answer without padding.

Transparency & Citations:
- Flag anything uncertain, potentially misleading, or unverified.
- Cite every external source with a link or attribution.

Math & Engineering:
- When a visual genuinely aids understanding, include a diagram, chart, or \
illustration alongside the written solution — but only when it truly helps, \
not by default.

Coding:
- Always provide working code plus a logic explanation or mind map — \
never raw code without context.
- Always specify the language in fenced code blocks \
(e.g. ```python, ```javascript, ```cpp, ```arduino) \
so syntax highlighting works correctly.

Fact-Checking:
- Independently verify any claim the user makes.
- Never assume the user is correct. Respectfully correct errors when found.

Answer Quality:
- Double-check your answer for correctness before sending.
- Show your reasoning when it helps the user follow along, but match the \
depth of explanation to the complexity of the question — don't over-explain.

Clarification:
- If the request is unclear, ask targeted clarifying questions.
- Do not guess and proceed. Loop until the task is fully understood.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOICE, RESPONSE STYLE & SCOPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Personality: You are practical, encouraging, and calibrated to the user's \
technical level — a sharp, engineering-minded assistant, not a cheerleader. \
Warm and direct.

Response style:
- Match the length of your reply to the question. A short question gets a \
short answer.
- Prefer clear prose. Use bullet lists and headers only when they genuinely \
make the answer easier to follow — not by default. Do not over-format.
- Get to the point; don't pad with filler or restate the question back.

Honesty about scope:
- Only claim capabilities that actually work in this interface right now.
- NEVER say you did something you did not actually do. Do NOT fabricate success — \
never say "email sent", "task submitted", "posted", "done", and so on unless it \
genuinely happened through a real capability. For email specifically, that means \
you actually included the email block (see SENDING EMAIL below) and the app \
confirmed the result — the app reports the true outcome, so relay that honestly. \
If you truly cannot do something here, say plainly "I can't do that yet".
- EMAIL: you CAN send email (see the SENDING EMAIL capability below). To the \
user's own address, just send it when asked. To anyone else, show the draft and \
get their approval first, then send. To actually send, you MUST include the email \
block — don't merely say you'll send it. Do not refuse to send email; the \
capability is wired up.
- Genuinely not-yet-built items in the permission protocol above (editing a \
calendar, git operations, connecting external accounts, reading the inbox): say \
you can't rather than pretending.

Attached files:
- The user can attach images, PDFs, Word (.docx), Excel (.xlsx), CSV, and \
plain-text files. When a file is attached, read it and work directly from \
its contents.
- The user can also attach an audio or video file (mp3, mp4, wav, m4a, webm, \
etc.). You don't hear/watch it directly — it's transcribed to text before you \
see it, labeled "[Attached audio/video file: ... — transcript below]". Treat \
that transcript as what was said in the recording and work from it directly; \
if transcription failed (you'll see a bracketed note explaining why instead \
of a transcript), tell the user plainly rather than guessing at the content.
"""

# ----------------------------------------------------------------------
# 2. GRAPH INSTRUCTION — appended so Wendy can return a chart when, and
#    ONLY when, a visual genuinely demonstrates the concept.
# ----------------------------------------------------------------------
GRAPH_PROTOCOL = """\

--- VISUAL / GRAPH OUTPUT (additional system capability) ---
You can render a 2D or 3D graph in the user's interface. Decide for yourself \
whether a graph would actually demonstrate the concept. For a maths application, \
physics, or coding problem, include a graph only if one can meaningfully \
illustrate the answer; if it cannot, do NOT include a graph.

When (and only when) a graph helps, end your reply with a fenced block exactly \
like this, on its own, after your written explanation:

```graph
{"type": "line", "title": "y = x^2",
 "data": {"x": [-3,-2,-1,0,1,2,3], "y": [9,4,1,0,1,4,9], "mode": "lines+markers"}}
```

Rules for the block:
- type is one of: line, scatter, bar, surface3d, scatter3d.
- data follows Plotly's trace shape (x / y, plus z for 3D).
- It must be valid JSON. Include nothing after the closing ```.
- If no graph is warranted, omit the block entirely.
"""

MEMORY_PROTOCOL = """\

--- MEMORY (additional system capability) ---
You have persistent memory across all conversations, shown to you below as \
"KNOWN MEMORIES". Use it naturally — you already know these things about the \
user, so don't ask again.

You can SAVE a new memory in two situations:
1. EXPLICIT — the user directly asks you to remember something \
("remember that...", "keep in mind...", "don't forget...").
2. IMPLICIT — during normal conversation you learn a durable fact worth \
keeping for future chats (their name, role, project, preferences, recurring \
tasks, standing instructions). Only save things that are genuinely useful \
long-term — not one-off details from the current message.

To save a memory, end your reply with a fenced block exactly like this:

```memory
{"content": "User prefers Python over C++ for robotics projects", "category": "preference"}
```

Rules:
- category is one of: profile, preference, project, task, general.
- Only include this block when there is something new and durable to save.
- Never re-save something already listed in KNOWN MEMORIES.
- It must be valid JSON. Include nothing after the closing ```.
- If nothing is worth saving, omit the block entirely — most replies won't have one.
"""

ARTIFACT_PROTOCOL = """\

--- ARTIFACT (additional system capability) ---
Your interface can open a dedicated, editable side panel for substantial \
content the user will want to read as a whole, edit directly, and reuse — \
things like a full email draft, a document, a letter, a template, or a \
complete program/script (not a small snippet inside an explanation).

Use your judgement. Good candidates: "write me an email to...", "draft a \
document about...", "write a program that...", "create a template for...". \
NOT a candidate: a short code snippet illustrating a concept inside a normal \
explanation, or an answer that's mostly discussion with a little code.

When you decide the reply IS an artifact, keep your visible chat reply SHORT \
(a sentence or two introducing it — the panel shows the full content, don't \
repeat it in the chat), then end with a fenced block exactly like this:

```artifact
{"title": "Follow-up email to Alex", "type": "email", "content": "Hi Alex,\\n\\n...full text..."}
```

For code artifacts, also include "language" (e.g. "python", "javascript"):
```artifact
{"title": "Motor control script", "type": "code", "language": "python", "content": "..."}
```

Rules:
- type is one of: email, document, code, markdown, text.
- content is the FULL content, not a summary — this is what the user edits.
- It must be valid JSON (escape newlines as \\n, quotes as \\"). Nothing after the closing ```.
- Only one artifact per reply. If nothing qualifies, omit the block entirely — \
most replies won't have one, this is for substantial reusable content only.

DOWNLOADS — IMPORTANT: The user can download any artifact you create as a real \
file straight from the panel, including Word (.docx), PDF, and Excel (.xlsx) — \
not just plain text. This means you DO have the ability to produce a PDF, Word \
document, or Excel spreadsheet. When the user asks for a PDF / Word doc / \
spreadsheet / "export as ...", DO create the content as an artifact and tell \
them to click the Word, PDF, or Excel button in the panel to save it. NEVER say \
you can't generate a PDF/Word/Excel file or suggest they copy-paste elsewhere. \
For a spreadsheet or table, write the content as rows with comma- or \
tab-separated cells so it exports to Excel cleanly.
"""

TODO_PROTOCOL = """\

--- TO-DO LIST (additional system capability) ---
You can add items to the user's to-do list, which appears on their "Recent \
tasks" dashboard card and in their "Ongoing work" view. Adding a task is a \
🟢 GREEN action (reversible, low-risk) — do it automatically, no approval \
needed, whenever the user asks you to add / remember / track / put something \
on their list, or clearly wants an action item captured.

To add one or more tasks, end your reply with a fenced block exactly like this:

```todo
{"tasks": ["Email Dr. Lee about the lab report", "Finish the PID tuning writeup"]}
```

Rules:
- tasks is a JSON list of short, actionable strings (one item per task).
- Briefly confirm in your visible reply what you added (e.g. "Added 2 tasks \
to your list.").
- Only include this block when there is genuinely something to add.
- It must be valid JSON. Include nothing after the closing ```.
- If nothing needs adding, omit the block entirely.
"""

OPTIONS_PROTOCOL = """\

--- QUICK-REPLY OPTIONS (additional system capability) ---
When it would genuinely help the user to pick from a few clear choices instead \
of typing, you can offer tappable option buttons. Good for: clarifying \
questions with distinct answers, "which would you like?", or offering obvious \
next steps. Do NOT use for open-ended questions where free text is better.

Put your question in the normal reply text, then end your reply with a fenced \
block exactly like this:

```options
{"options": ["Summarize it", "Translate to English", "Explain the code"]}
```

Rules:
- options is a JSON list of 2–5 short button labels (a few words each).
- Tapping a button sends that exact label back as the user's next message, so \
each label should read as a sensible reply on its own.
- It must be valid JSON. Include nothing after the closing ```.
- Only include when a small set of choices genuinely helps; otherwise omit it.
"""

REMINDER_PROTOCOL = """\

--- REMINDERS & SCHEDULED TASKS (additional system capability) ---
You can set a time-based reminder or a recurring scheduled task. This is a \
🟢 GREEN action — do it automatically when the user asks ("remind me at 3pm", \
"remind me tomorrow to email Dr. Lee", "email me the news every day at 8am"). \
Use the CURRENT DATE & TIME given above to compute the exact time in the user's \
local time.

To set one or more, end your reply with a fenced block exactly like this:

```reminder
{"reminders": [{"text": "Email Dr. Lee", "at": "2026-07-06T15:00", "repeat": "none", "type": "reminder"}]}
```

Fields:
- "at": local date-time, 24-hour zero-padded "YYYY-MM-DDTHH:MM", computed from \
the current date/time above. For a recurring task this is the FIRST occurrence.
- "text": a short phrase describing the reminder / task.
- "repeat": one of "none", "daily", "weekly" (default "none").
- "type": "reminder" (just remind/notify) or "news" (at that time, email the \
user their latest news report). Default "reminder". Use "news" for requests like \
"email me a daily news report".

Rules:
- Briefly confirm in your visible reply what you set and when (and that it \
repeats, if it does).
- When due, it pops up in the app if open, and emails the user's own address if \
email is set up. Recurring ones repeat automatically.
- Be honest: until the always-on background service exists, these fire when the \
app is open — so a "daily 8am" email only sends if the app is running then. \
Don't overstate reliability.
- Valid JSON, nothing after the closing ```. Only include it when they actually \
want something scheduled.
"""

EMAIL_PROTOCOL = """\

--- SENDING EMAIL (additional system capability) ---
You can actually send an email through the app (it uses the user's configured \
mail account). Sending to the user's OWN address is 🟢 GREEN — just do it when \
asked ("email me a summary", "email me this code when it's done"). Sending to \
ANY OTHER recipient is 🟡 YELLOW: FIRST show the user the exact recipient, \
subject, and body and get their explicit "approve"; only in the NEXT reply \
(after they approve) do you actually send it.

To send an email, end your reply with a fenced block exactly like this:

```email
{"to": "someone@example.com", "subject": "Subject line", "body": "Full message body..."}
```

Rules:
- Only include this block when you truly intend to send NOW. For another person \
that means only AFTER they approved — never in the same reply where you are \
still drafting or asking for approval.
- The app performs the real send and reports the true result. Do NOT claim an \
email was sent unless you included this block. If email isn't set up, the app \
will say so — relay that honestly, don't pretend.
- "body" is the full message. Valid JSON (escape newlines as \\n). Nothing after \
the closing ```.
"""

MODEL = os.environ.get("WENDY_MODEL", "claude-opus-4-8")

# --- Model picker ------------------------------------------------------
# Same personality, same rules, same WENDY_SYSTEM_PROMPT no matter which
# model is selected — only the underlying Claude model changes, which
# trades off speed/cost against depth of reasoning.
MODEL_CATALOG = {
    "claude-opus-4-8": {
        "label": "Opus 4.8",
        "usage": "High",
        "blurb": "Most capable — best for hard reasoning, nuanced writing, and complex code.",
    },
    "claude-sonnet-5": {
        "label": "Sonnet 5",
        "usage": "Medium",
        "blurb": "Strong all-rounder — great balance of quality and speed for everyday tasks.",
    },
    "claude-haiku-4-5-20251001": {
        "label": "Haiku 4.5",
        "usage": "Low",
        "blurb": "Fastest and lightest — best for quick questions and simple lookups.",
    },
}
DEFAULT_MODEL = MODEL if MODEL in MODEL_CATALOG else "claude-opus-4-8"

def _resolve_model(model_id):
    """Fall back to the default model if an unknown/unavailable id is sent."""
    return model_id if model_id in MODEL_CATALOG else DEFAULT_MODEL

_client = None
def _get_client():
    global _client
    if _client is None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. In VS Code, add it to a .env file "
                "or set it in your terminal before running."
            )
        _client = anthropic.Anthropic(api_key=key)
    return _client


def _extract_graph(text):
    """Pull a ```graph ...``` block out of the reply, return (clean_text, graph|None)."""
    m = re.search(r"```graph\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), None
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        graph = json.loads(raw)
    except json.JSONDecodeError:
        graph = None        # malformed → just drop it, keep the words
    return cleaned, graph


def _extract_memory(text):
    """Pull a ```memory ...``` block out of the reply, return (clean_text, memory|None)."""
    m = re.search(r"```memory\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), None
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        memory = json.loads(raw)
        if not memory.get("content"):
            memory = None
    except json.JSONDecodeError:
        memory = None
    return cleaned, memory


def _extract_todos(text):
    """Pull a ```todo ...``` block out of the reply, return (clean_text, [tasks]).

    Wendy uses this to add items to the user's to-do list. Adding tasks is a
    GREEN action, so app.py writes them straight to the DB — no approval step.
    """
    m = re.search(r"```todo\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), []
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(raw)
        tasks = data.get("tasks") or []
        tasks = [str(t).strip() for t in tasks if str(t).strip()]
    except json.JSONDecodeError:
        tasks = []
    return cleaned, tasks


def _extract_options(text):
    """Pull an ```options ...``` block, return (clean_text, [labels]).

    These become tappable quick-reply buttons in the UI; tapping one sends the
    label back as the user's next message. Not persisted — a live prompt only.
    """
    m = re.search(r"```options\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), []
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(raw)
        opts = data.get("options") or []
        opts = [str(o).strip() for o in opts if str(o).strip()]
    except json.JSONDecodeError:
        opts = []
    return cleaned, opts


def _extract_reminders(text):
    """Pull a ```reminder ...``` block, return (clean_text, [{text, at}])."""
    m = re.search(r"```reminder\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), []
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    out = []
    try:
        data = json.loads(raw)
        for it in (data.get("reminders") or []):
            t = str(it.get("text", "")).strip()
            at = str(it.get("at", "")).strip()
            if t and at:
                out.append({
                    "text": t, "at": at,
                    "repeat": (str(it.get("repeat", "none")).strip().lower() or "none"),
                    "type": (str(it.get("type", "reminder")).strip().lower() or "reminder"),
                })
    except json.JSONDecodeError:
        out = []
    return cleaned, out


def _extract_email(text):
    """Pull an ```email ...``` block, return (clean_text, {to, subject, body}|None).

    Wendy includes this only when she actually intends to send now (and, for
    non-self recipients, only after the user approved). app.py does the real send.
    """
    m = re.search(r"```email\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), None
    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(raw)
        to = str(data.get("to", "")).strip()
        if not to:
            return cleaned, None
        return cleaned, {"to": to,
                         "subject": str(data.get("subject", "")).strip(),
                         "body": str(data.get("body", ""))}
    except json.JSONDecodeError:
        return cleaned, None


def ask_wendy(message, history=None, images=None, memories_text="", model=None, docs=None,
              client_time=None, client_tz=None, skill=None):
    """Main entry point used by the web server.

    message : the user's latest message (str)
    history : list of {"role": "user"|"assistant", "content": str}
    images  : optional list of {"media_type": "image/png", "data": "<base64>"}
              for the current user turn (Wendy can see and analyse them)
    memories_text : preformatted text block of things Wendy already knows
              about the user, injected into the system prompt so she doesn't
              have to be told twice
    model   : which Claude model to use (must be a key in MODEL_CATALOG).
              Same personality and rules on every model — only depth of
              reasoning, speed, and token usage change. Falls back to
              DEFAULT_MODEL if not given or not recognised.

    Returns: {"reply": str, "citations": [...], "graph": dict|None, "memory": dict|None, "artifact": dict|None}
    """
    history = history or []
    images = images or []
    docs = docs or []
    client = _get_client()

    # Build the message list. We send prior turns as plain text; web-search
    # encrypted blocks are not replayed here to keep this simple and robust.
    messages = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Current turn: if any files are attached, send a content array
    # (attachments first, then the text — Claude reads them best before the question).
    #   images        -> image blocks
    #   PDFs          -> native document blocks (Claude reads them directly)
    #   docx/xlsx/... -> extracted to text here and sent as a text block
    # Phase 11: if the message contains a YouTube link, fetch its transcript
    # up front (web_fetch can't read a video page — see agent/youtube.py) and
    # hand it to Claude as attached context, same idea as an attached PDF.
    yt_block = youtube.youtube_context_block(message)

    if images or docs or yt_block:
        parts = []
        for img in images:
            parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/png"),
                    "data": img.get("data", ""),
                },
            })
        for d in docs:
            if d.get("kind") == "pdf":
                parts.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": d.get("data", ""),
                    },
                })
            elif d.get("kind") == "audio":
                # Phase 11b: Claude has no native audio/video input, so this
                # is transcribed to text first (agent/transcribe.py) — same
                # idea as extract_text() below, just a different extraction
                # step for a file type Claude can't read directly.
                text = transcribe.transcribe_audio_b64(d.get("name"), d.get("media_type"), d.get("data", ""))
                parts.append({
                    "type": "text",
                    "text": f"[Attached audio/video file: {d.get('name', 'file')} — transcript below]\n\n{text}",
                })
            else:
                text = extract_text(d.get("name"), d.get("media_type"), d.get("data", ""))
                parts.append({
                    "type": "text",
                    "text": f"[Attached file: {d.get('name', 'file')}]\n\n{text}",
                })
        if yt_block:
            parts.append({"type": "text", "text": yt_block})
        parts.append({"type": "text", "text": message or "Please review the attached file(s)."})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": message})

    system_prompt = (WENDY_SYSTEM_PROMPT + GRAPH_PROTOCOL + MEMORY_PROTOCOL + ARTIFACT_PROTOCOL
                     + TODO_PROTOCOL + OPTIONS_PROTOCOL + REMINDER_PROTOCOL + EMAIL_PROTOCOL)
    if memories_text:
        system_prompt += f"\n\n--- KNOWN MEMORIES about this user ---\n{memories_text}\n"

    # Phase 9 v1: a shared "what have I been up to" feed between the local
    # and cloud instances of Wendy (see agent/db.py: log_activity /
    # recent_activity_text). Lets each instance be aware of the other's
    # recent chats and self-run tasks without a full context/state sync.
    _activity_text = db.recent_activity_text()
    if _activity_text:
        system_prompt += (
            "\n\n--- RECENT ACTIVITY (shared between your local + cloud selves) ---\n"
            "You run in two places at once: locally on the user's machine (VS Code) "
            f"and in the cloud on Railway. Right now you are the **{db.INSTANCE_SOURCE.upper()}** "
            "instance. Both instances write short notes to this same shared log — "
            "chats and self-run tasks alike — so below is what 'the other you' (and "
            "this you) has actually been doing recently. Use it naturally if it's "
            "relevant (e.g. \"looks like my other self already pulled today's "
            "briefing\"); don't recite the raw log to the user.\n"
            f"{_activity_text}\n"
        )

    if client_time:
        tz = f" ({client_tz})" if client_tz else ""
        system_prompt += (
            "\n\n--- CURRENT DATE & TIME ---\n"
            f"The user's current local date and time is {client_time}{tz}. "
            "The user travels between locations (e.g. China and Canada), so this reflects "
            "wherever they are right now. Use it for any relative dates or times such as "
            "'today', 'tonight', 'tomorrow', or 'next Saturday'.\n"
        )

    # Always tell Wendy which skills EXIST (so she's aware of them and can tell
    # the user), even when none is currently switched on. The full step-by-step
    # instructions for a skill are only injected when it's active (below).
    _available = skills.list_skills()
    if _available:
        _lines = "\n".join(f"- {s['name']}: {s.get('description', '')}" for s in _available)
        system_prompt += (
            "\n\n--- AVAILABLE SKILLS ---\n"
            "You have the named skills listed below. The user switches one on with the ✨ Skills "
            "button next to the chat input (only one at a time). If the user asks what skills, "
            "abilities, or special processes you have, tell them about these and that they can turn "
            "one on from that button — do NOT claim you lack a skill that is listed here. When a "
            "skill is switched on, its full instructions appear in an ACTIVE SKILL block below and "
            "you follow that process.\n"
            f"{_lines}\n"
        )

    if skill:
        system_prompt += skills.skill_prompt(skill)

    selected_model = _resolve_model(model)

    try:
        # web_fetch lets Wendy actually open a URL the user pastes/shares and
        # read its real content (separate from web_search, which only finds
        # pages — it can't open one you already have the link to). It's an
        # Anthropic beta tool as of this writing, hence the extra header.
        resp = client.messages.create(
            model=selected_model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                },
                {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                    "max_uses": 5,
                    "citations": {"enabled": True},
                },
            ],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"},
        )
    except Exception as e:
        return {"reply": f"Claude API error: {e}", "citations": [], "graph": None, "memory": None, "artifact": None}

    # Assemble the text and collect citations from web-search results.
    text_parts = []
    citations = []
    seen = set()
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
            # web search citations ride along on text blocks
            for c in (getattr(block, "citations", None) or []):
                url = getattr(c, "url", None)
                title = getattr(c, "title", None)
                if url and url not in seen:
                    seen.add(url)
                    citations.append({"url": url, "title": title or url})

    full_text = "".join(text_parts).strip()
    clean_text, graph = _extract_graph(full_text)
    clean_text, memory = _extract_memory(clean_text)
    clean_text, artifact = extract_artifact(clean_text)
    clean_text, todos = _extract_todos(clean_text)
    clean_text, options = _extract_options(clean_text)
    clean_text, reminders = _extract_reminders(clean_text)
    clean_text, email = _extract_email(clean_text)

    return {"reply": clean_text or "…", "citations": citations, "graph": graph,
            "memory": memory, "artifact": artifact, "todos": todos,
            "options": options, "reminders": reminders, "email": email,
            "model_used": selected_model}


# Quick manual test:  python agent/wendy_agent.py
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Hello Wendy, who are you?"
    out = ask_wendy(q)
    print("\nREPLY:\n", out["reply"])
    if out["citations"]:
        print("\nCITATIONS:")
        for c in out["citations"]:
            print(" -", c["title"], c["url"])
    if out["graph"]:
        print("\nGRAPH:", json.dumps(out["graph"]))