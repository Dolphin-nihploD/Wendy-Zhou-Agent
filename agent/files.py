"""
agent/files.py
==============
Lets Wendy generate downloadable files directly from chat.

Wendy signals a file by appending a special fenced block to her reply:

```file
{
  "filename": "robot_motor.py",
  "type": "python",
  "content": "# full file content here..."
}
```

Supported types:
  text     -> .txt
  markdown -> .md
  python   -> .py
  javascript -> .js
  csv      -> .csv
  json     -> .json
  html     -> .html
  cpp      -> .cpp
  java     -> .java

The file block is stripped from the visible reply and returned separately
so the UI can show a download button.
"""

import re
import json
import base64
import os
import tempfile
import datetime

# MIME types for each file type
MIME_TYPES = {
    "text":       "text/plain",
    "markdown":   "text/markdown",
    "python":     "text/x-python",
    "javascript": "text/javascript",
    "csv":        "text/csv",
    "json":       "application/json",
    "html":       "text/html",
    "cpp":        "text/x-c++src",
    "java":       "text/x-java",
    "bash":       "text/x-shellscript",
}

EXTENSIONS = {
    "text":       ".txt",
    "markdown":   ".md",
    "python":     ".py",
    "javascript": ".js",
    "csv":        ".csv",
    "json":       ".json",
    "html":       ".html",
    "cpp":        ".cpp",
    "java":       ".java",
    "bash":       ".sh",
}


def extract_artifact(text):
    """
    Pull a ```artifact {...} ``` block from Wendy's reply.

    This is the trigger for the editable side-panel feature: Wendy uses this
    (instead of a plain ```file block) when the WHOLE reply is a document,
    email, template, or program meant to be opened, edited, and reused --
    not just a snippet inside a normal explanation.

    Returns:
        (clean_text, artifact_info | None)

    artifact_info = {
        "title": "Follow-up email to Alex",
        "type": "email",           # email | document | code | markdown | text
        "language": "python",      # only meaningful when type == "code"
        "content": "...",
        "filename": "followup_email.txt"
    }
    """
    pattern = r"```artifact\s*(\{.*?\})\s*```"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return text.strip(), None

    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return cleaned, None

    atype    = (data.get("type") or "document").lower()
    language = (data.get("language") or "").lower()
    content  = data.get("content", "")
    title    = data.get("title") or "Untitled"

    ext_key = language if atype == "code" and language in EXTENSIONS else \
              ("markdown" if atype in ("document", "email", "markdown") else "text")
    ext = EXTENSIONS.get(ext_key, ".txt")
    safe_name = re.sub(r"[^\w\- ]", "", title).strip().replace(" ", "_") or "wendy_artifact"

    return cleaned, {
        "title":    title,
        "type":     atype,
        "language": language,
        "content":  content,
        "filename": f"{safe_name}{ext}",
    }


def extract_file(text):
    """
    Pull a ```file {...} ``` block from Wendy's reply.

    Returns:
        (clean_text, file_info | None)

    file_info = {
        "filename": "example.py",
        "type": "python",
        "content": "...",
        "mime": "text/x-python",
        "size": 1234,
        "b64": "<base64-encoded content>"
    }
    """
    pattern = r"```file\s*(\{.*?\})\s*```"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return text.strip(), None

    raw = m.group(1)
    cleaned = (text[:m.start()] + text[m.end():]).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return cleaned, None

    ftype    = data.get("type", "text").lower()
    content  = data.get("content", "")
    filename = data.get("filename", f"wendy_output{EXTENSIONS.get(ftype, '.txt')}")
    mime     = MIME_TYPES.get(ftype, "text/plain")

    # encode to base64 so we can send it safely over JSON
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    return cleaned, {
        "filename": filename,
        "type":     ftype,
        "content":  content,
        "mime":     mime,
        "size":     len(content.encode("utf-8")),
        "b64":      b64,
    }


def save_temp_file(file_info):
    """
    Save file_info content to a temp file and return the path.
    Used by the Flask /api/download endpoint.
    """
    suffix = EXTENSIONS.get(file_info["type"], ".txt")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(file_info["content"])
        return f.name
