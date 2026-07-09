"""
app.py — Wendy Zhou web server
==============================
Serves the dashboard / chat / ongoing-work / calendar interface and connects
the chat to the Wendy agent (agent/wendy_agent.py), which calls the Anthropic
Claude API with web search + citations.

RUN IT (in VS Code terminal)
----------------------------
    pip install flask anthropic
    set ANTHROPIC_API_KEY=sk-ant-...      (Windows)   /   export ... (mac/Linux)
    python app.py
Then open http://127.0.0.1:5000
"""

import os
import json
import datetime

# Load a local .env file if python-dotenv is installed (handy in VS Code).
# Falls back silently to real environment variables if it isn't.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify, Response

from agent.wendy_agent import ask_wendy, MODEL_CATALOG, DEFAULT_MODEL
from agent.news import fetch_news, get_news_briefing
from agent.stocks import fetch_watchlist
from agent.weather import fetch_weather
from agent.briefing import generate_briefing
from agent import db

app = Flask(__name__)
db.init_db()   # create tables if they don't exist yet (safe to call every startup)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    images = body.get("images") or []
    docs = body.get("docs") or []
    client_time = body.get("client_time") or ""
    client_tz = body.get("client_tz") or ""
    skill = body.get("skill") or ""
    conversation_id = body.get("conversation_id")
    model = body.get("model") or DEFAULT_MODEL
    if model not in MODEL_CATALOG:
        model = DEFAULT_MODEL
    if not message and not images and not docs:
        return jsonify({"reply": "Send a message and I'll help.", "citations": [], "graph": None})

    # create a conversation row on the first message of a new chat
    if not conversation_id:
        title = (message or "Image").strip()[:40] or "New chat"
        conversation_id = db.create_conversation(title=title)

    try:
        memories_text = db.memories_as_text()
        result = ask_wendy(message, history, images, memories_text=memories_text, model=model,
                           docs=docs, client_time=client_time, client_tz=client_tz, skill=skill)
    except Exception as e:
        result = {"reply": f"Something went wrong: {e}", "citations": [], "graph": None, "memory": None}

    # persist both turns
    try:
        db.add_message(conversation_id, "user", message, images)
        db.add_message(conversation_id, "assistant", result.get("reply", ""), artifact=result.get("artifact"))
        mem = result.get("memory")
        if mem and mem.get("content"):
            db.add_memory(mem["content"], mem.get("category", "general"))
        # GREEN action: Wendy can add to-dos to the user's list without approval
        for task in (result.get("todos") or []):
            if task:
                db.add_todo(task)
        # GREEN action: Wendy can set time-based / recurring reminders without approval
        for rem in (result.get("reminders") or []):
            if rem.get("text") and rem.get("at"):
                db.add_reminder(rem["text"], rem["at"],
                                rem.get("repeat", "none"), rem.get("type", "reminder"))
        # Phase 9 v1: log this chat to the shared activity feed (see agent/db.py)
        if message:
            db.log_activity("chat", f"Chatted with user: {message[:150]}")
        else:
            db.log_activity("chat", "Chatted with user (file/image attachment, no text)")
    except Exception as e:
        print(f"warning: failed to persist chat/memory: {e}")

    # If Wendy included an email block, actually send it and report the TRUE result
    email = result.get("email")
    if email and email.get("to"):
        from agent import mailer
        ok, msg = mailer.send_email(email["to"], email.get("subject", ""), email.get("body", ""))
        result["email_result"] = {"ok": ok, "message": msg, "to": email["to"]}
        if ok:
            try:
                db.log_activity("task", f"Sent email to {email['to']}: {email.get('subject', '')}")
            except Exception as e:
                print(f"warning: failed to log email activity: {e}")

    result["conversation_id"] = conversation_id
    return jsonify(result)


@app.route("/api/conversations")
def api_list_conversations():
    return jsonify(db.list_conversations())


@app.route("/api/conversations", methods=["POST"])
def api_create_conversation():
    body = request.get_json(force=True, silent=True) or {}
    conv_id = db.create_conversation(title=body.get("title", "New chat"))
    return jsonify({"id": conv_id})


@app.route("/api/conversations/<int:conv_id>")
def api_get_conversation(conv_id):
    return jsonify(db.get_messages(conv_id))


@app.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
def api_delete_conversation(conv_id):
    db.delete_conversation(conv_id)
    return jsonify({"deleted": conv_id})


@app.route("/api/conversations/<int:conv_id>/rename", methods=["POST"])
def api_rename_conversation(conv_id):
    body = request.get_json(force=True, silent=True) or {}
    db.rename_conversation(conv_id, body.get("title", "New chat"))
    return jsonify({"renamed": conv_id})


@app.route("/api/conversations/<int:conv_id>/pin", methods=["POST"])
def api_pin_conversation(conv_id):
    body = request.get_json(force=True, silent=True) or {}
    pinned = bool(body.get("pinned", True))
    db.pin_conversation(conv_id, pinned)
    return jsonify({"pinned": pinned})


@app.route("/api/memories")
def api_list_memories():
    return jsonify(db.list_memories())


@app.route("/api/memories", methods=["POST"])
def api_add_memory():
    body = request.get_json(force=True, silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    db.add_memory(content, body.get("category", "general"))
    return jsonify({"added": True})


@app.route("/api/memories/<int:memory_id>", methods=["DELETE"])
def api_delete_memory(memory_id):
    db.delete_memory(memory_id)
    return jsonify({"deleted": memory_id})


# ------------------------------------------------------------------ todos --
@app.route("/api/todos")
def api_list_todos():
    return jsonify(db.list_todos())


@app.route("/api/todos", methods=["POST"])
def api_add_todo():
    body = request.get_json(force=True, silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    todo_id = db.add_todo(content)
    return jsonify({"id": todo_id, "added": True})


@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
def api_delete_todo(todo_id):
    db.delete_todo(todo_id)
    return jsonify({"deleted": todo_id})


@app.route("/api/todos/<int:todo_id>/toggle", methods=["POST"])
def api_toggle_todo(todo_id):
    body = request.get_json(force=True, silent=True) or {}
    done = bool(body.get("done", True))
    db.set_todo_done(todo_id, done)
    return jsonify({"id": todo_id, "done": done})


# --------------------------------------------------------------- reminders --
@app.route("/api/reminders")
def api_list_reminders():
    return jsonify(db.list_reminders())


@app.route("/api/reminders", methods=["POST"])
def api_add_reminder():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    at = (body.get("at") or "").strip()
    if not text or not at:
        return jsonify({"error": "text and at are required"}), 400
    rid = db.add_reminder(text, at)
    return jsonify({"id": rid, "added": True})


@app.route("/api/reminders/<int:reminder_id>", methods=["DELETE"])
def api_delete_reminder(reminder_id):
    db.delete_reminder(reminder_id)
    return jsonify({"deleted": reminder_id})


def _next_occurrence(remind_at, recurrence, now_iso):
    """Next fire time for a recurring reminder, as a local ISO string, or None
    for a one-off. Advances by the interval, skipping any missed occurrences so
    we don't fire repeatedly for a long-closed app."""
    recurrence = (recurrence or "none").lower()
    if recurrence not in ("daily", "weekly"):
        return None
    try:
        dt = datetime.datetime.fromisoformat(remind_at)
        now = datetime.datetime.fromisoformat(now_iso)
    except Exception:
        return None
    delta = datetime.timedelta(days=1 if recurrence == "daily" else 7)
    dt = dt + delta
    while dt <= now:
        dt = dt + delta
    return dt.strftime("%Y-%m-%dT%H:%M")


@app.route("/api/reminders/due", methods=["POST"])
def api_due_reminders():
    """Return reminders that are now due (given the browser's local 'now'), email
    the user for each (self-notification carve-out), then advance recurring ones
    to their next occurrence or mark one-offs fired. Runs whenever the app is open."""
    from agent import mailer
    body = request.get_json(force=True, silent=True) or {}
    now = (body.get("now") or "").strip()
    if not now:
        return jsonify({"due": []})

    fired = []
    for r in db.due_reminders(now):
        kind = r.get("kind", "reminder")
        if kind == "news":
            display = "News report emailed" if mailer.is_configured() else "News report is ready"
            try:
                report = get_news_briefing(days_back=7)
            except Exception as e:
                report = f"(couldn't build the news report: {e})"
            subject, emailbody = "Your news report", report
        else:
            display = r["text"]
            subject = "Reminder: " + r["text"]
            emailbody = f"Reminder from Wendy:\n\n{r['text']}\n\n(scheduled for {r['remind_at']})"

        if mailer.is_configured():
            mailer.send_self_email(subject, emailbody)

        nxt = _next_occurrence(r["remind_at"], r.get("recurrence", "none"), now)
        if nxt:
            db.advance_reminder(r["id"], nxt)
        else:
            db.mark_reminder_fired(r["id"])

        # Phase 9 v1: this is a self-run task (nobody was actively chatting
        # when it fired), so it belongs in the shared activity feed too.
        try:
            if kind == "news":
                db.log_activity("task", "Sent the scheduled daily news report email"
                                        if mailer.is_configured() else
                                        "A scheduled news report was due (email not configured)")
            else:
                db.log_activity("task", f"Reminder fired: {r['text']}")
        except Exception as e:
            print(f"warning: failed to log reminder activity: {e}")

        fired.append({"text": display})

    return jsonify({"due": fired})


@app.route("/api/email/test", methods=["POST"])
def api_email_test():
    """Send yourself a test email to check the SMTP setup."""
    from agent import mailer
    if not mailer.is_configured():
        return jsonify({"ok": False,
                        "message": "Email isn't set up. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your .env file."})
    ok, msg = mailer.send_self_email(
        "Wendy test email",
        "This is a test email from Wendy. If you're reading this, email sending works.",
    )
    return jsonify({"ok": ok, "message": msg})


# --------------------------------------------------------- conversation search --
@app.route("/api/conversations/search")
def api_search_conversations():
    """Keyword search across all past messages. ?q=<term>."""
    q = (request.args.get("q") or "").strip()
    return jsonify({"query": q, "results": db.search_messages(q)})


# ------------------------------------------------------------- data export --
@app.route("/api/export")
def api_export():
    """Download a full backup (memories + to-dos + conversations) as JSON.

    Green-zone action: read-only, gives the user a backup they can keep
    independent of Railway/Postgres.
    """
    data = db.export_all()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="wendy_backup_{stamp}.json"'},
    )


@app.route("/api/conversations/<int:conv_id>/export")
def api_export_conversation(conv_id):
    """Download one conversation as a real document: ?format=md|docx|pdf.

    md   -> plain markdown (text)
    docx -> Microsoft Word   (python-docx)
    pdf  -> PDF              (reportlab)
    """
    from agent import exporters

    fmt = (request.args.get("format") or "md").lower()
    messages = db.get_messages(conv_id)
    titles = {c["id"]: c.get("title") for c in db.list_conversations()}
    title = titles.get(conv_id) or "Conversation"
    fname = exporters.safe_filename(title)

    try:
        if fmt == "docx":
            data = exporters.conversation_to_docx(title, messages)
            return Response(
                data,
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="{fname}.docx"'},
            )
        if fmt == "pdf":
            data = exporters.conversation_to_pdf(title, messages)
            return Response(
                data,
                mimetype="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'},
            )
    except Exception as e:
        # missing library or a build error -> explain instead of a blank 500
        return jsonify({"error": f"Could not build {fmt.upper()}: {e}"}), 500

    # default: markdown
    md = exporters.conversation_to_md(title, messages)
    return Response(
        md,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{fname}.md"'},
    )


@app.route("/api/artifact/export", methods=["POST"])
def api_artifact_export():
    """Turn an artifact's current content into a real Word/PDF/Excel file.

    POST body: {title, content, format} where format is docx | pdf | xlsx.
    The frontend sends the (possibly edited) panel content, so the download
    always matches what the user sees.
    """
    from agent import exporters

    body = request.get_json(force=True, silent=True) or {}
    title = (body.get("title") or "document").strip()
    content = body.get("content") or ""
    fmt = (body.get("format") or "docx").lower()
    fname = exporters.safe_filename(title, "document")

    builders = {
        "docx": (exporters.text_to_docx,
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
        "pdf":  (exporters.text_to_pdf, "application/pdf", "pdf"),
        "xlsx": (exporters.text_to_xlsx,
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    }
    if fmt not in builders:
        return jsonify({"error": f"Unknown format: {fmt}"}), 400

    build, mime, ext = builders[fmt]
    try:
        data = build(title, content)
    except Exception as e:
        return jsonify({"error": f"Could not build {fmt.upper()}: {e}"}), 500

    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}.{ext}"'},
    )


@app.route("/api/skills")
def api_skills():
    """List Wendy's available skills for the ✨ Skills picker."""
    from agent import skills
    return jsonify(skills.list_skills())


@app.route("/api/models")
def api_models():
    """List available Claude models for the model picker (id, label, usage level, blurb)."""
    return jsonify({
        "default": DEFAULT_MODEL,
        "models": [
            {"id": k, **v} for k, v in MODEL_CATALOG.items()
        ],
    })


@app.route("/api/context")
def api_context():
    now = datetime.datetime.now()
    hour = now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    try:
        date_str = now.strftime("%A, %B %-d, %Y")
    except ValueError:                      # Windows doesn't support %-d
        date_str = now.strftime("%A, %B %d, %Y")
    return jsonify({
        "date": date_str,
        "greeting": greeting,
        "agent_connected": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    })


@app.route("/api/news")
def api_news():
    """Fetch and return recent news articles as JSON."""
    days_back = request.args.get("days", 7, type=int)
    result = fetch_news(days_back=days_back, max_articles=8)
    return jsonify(result)


@app.route("/api/news-briefing")
def api_news_briefing():
    """Get a markdown-formatted news briefing for Wendy to read aloud."""
    days_back = request.args.get("days", 7, type=int)
    briefing = get_news_briefing(days_back=days_back)
    return jsonify({"briefing": briefing})


@app.route("/api/stocks")
def api_stocks():
    """Return current quotes for the watchlist."""
    return jsonify(fetch_watchlist())


@app.route("/api/weather")
def api_weather():
    """Return current weather + 3-day forecast for the configured location."""
    return jsonify(fetch_weather())


@app.route("/api/briefing")
def api_briefing():
    """Return today's daily briefing (cached once per day; ?force=1 to regenerate)."""
    force = request.args.get("force", "0") in ("1", "true", "yes")
    return jsonify(generate_briefing(force=force))


if __name__ == "__main__":
    connected = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    port = int(os.environ.get("PORT", 5000))
    print(f"Wendy Zhou running on http://0.0.0.0:{port}")
    print("ANTHROPIC_API_KEY:", "set ✓" if connected else "NOT set ✗  (chat will error until you set it)")
    app.run(host="0.0.0.0", port=port, debug=False)