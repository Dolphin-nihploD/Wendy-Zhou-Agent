"""
agent/youtube.py
=================
Phase 11 — lets Wendy actually read a YouTube video's transcript when the
user shares a link.

Why this needs its own path instead of the web_fetch tool: a YouTube watch
page is a JS single-page app — the raw HTML web_fetch sees has no transcript
text in it, only a player shell. YouTube also rate-limits (429) generic
fetches of video pages. So instead we talk directly to YouTube's caption
data via the youtube-transcript-api library (no API key needed).

Wired into wendy_agent.ask_wendy(): before calling Claude, we scan the
user's message for YouTube links, fetch each transcript, and hand it to
Claude as attached context (same idea as an attached PDF) — no extra tool
round-trip, no extra Claude API call.

LIMITATIONS — be upfront with the user, don't silently fail:
- Only works for videos that HAVE captions (auto-generated or uploaded).
- As of 2026, YouTube blocks a LOT of unauthenticated transcript requests —
  not just obvious cloud/data-center IPs, plenty of home connections get
  blocked too (confirmed 2026-07-09: blocked even from the user's own local
  machine, not just Railway). The library's own error message says as much
  ("too many requests" OR "an IP belonging to a cloud provider"). The
  library's documented fix is routing through a proxy — see PROXY SUPPORT
  below. Without one, transcript fetching may simply fail outright.
- If it happens we return a clear per-video error string instead of
  crashing, and Wendy is instructed (via the error text itself) to relay it
  honestly rather than pretend she read the video.

PROXY SUPPORT (added 2026-07-09 after real IP-blocking hit in testing) ---
Set these in .env to route transcript fetches through a proxy:
  WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD
      Recommended — this is the provider youtube-transcript-api is built
      to use (rotating residential IPs, has a free tier to try). Sign up
      at webshare.io, grab your "Proxy" credentials (not your account
      login), and put them here.
  PROXY_HTTP_URL / PROXY_HTTPS_URL
      Any other HTTP(S) proxy instead, e.g. "http://user:pass@host:port".
If neither is set, requests go out unproxied (the original behavior) —
which is exactly what just got blocked, so at least one of these needs to
be configured for this feature to work reliably.
"""

import os
import re

_MAX_TRANSCRIPT_CHARS = 12000  # keep prompts a reasonable size

# Matches youtube.com/watch?v=ID, youtu.be/ID, /shorts/ID, /embed/ID, /live/ID
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)


def find_video_ids(text):
    """De-duplicated, order-preserving list of YouTube video IDs found in `text`."""
    if not text:
        return []
    seen = set()
    ids = []
    for m in _YT_URL_RE.finditer(text):
        vid = m.group(1)
        if vid not in seen:
            seen.add(vid)
            ids.append(vid)
    return ids


def _get_proxy_config():
    """Build a proxy config from .env, or None if no proxy is configured.

    See the PROXY SUPPORT note at the top of this file for why this exists —
    without a proxy, YouTube blocks a large fraction of transcript requests
    outright, cloud or not.
    """
    ws_user = os.environ.get("WEBSHARE_PROXY_USERNAME", "").strip()
    ws_pass = os.environ.get("WEBSHARE_PROXY_PASSWORD", "").strip()
    if ws_user and ws_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        return WebshareProxyConfig(proxy_username=ws_user, proxy_password=ws_pass)

    http_url = os.environ.get("PROXY_HTTP_URL", "").strip()
    https_url = os.environ.get("PROXY_HTTPS_URL", "").strip()
    if http_url or https_url:
        from youtube_transcript_api.proxies import GenericProxyConfig
        return GenericProxyConfig(http_url=http_url or https_url, https_url=https_url or http_url)

    return None


def _fetch_raw_transcript(video_id):
    """Return a list of {"text": ...} snippets.

    youtube-transcript-api changed its API shape around v1.0 (instance-based
    `.fetch()` vs. the older classmethod `.get_transcript()`) — try the new
    shape first and fall back, so this works whichever version is installed.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    proxy_config = _get_proxy_config()
    try:
        api = YouTubeTranscriptApi(proxy_config=proxy_config) if proxy_config else YouTubeTranscriptApi()
    except AttributeError:
        # pre-1.0 library: only the static classmethod exists (no proxy support)
        return YouTubeTranscriptApi.get_transcript(video_id)
    except TypeError:
        # constructor doesn't accept proxy_config on this version — fall back
        # to unproxied rather than crashing outright
        api = YouTubeTranscriptApi()

    try:
        fetched = api.fetch(video_id)
        return [{"text": getattr(s, "text", "")} for s in fetched]
    except Exception as first_err:
        # Default fetch prefers English and can fail outright for a video
        # whose only transcript is in another language. Before giving up,
        # take WHATEVER transcript actually exists (any language) rather
        # than reporting "unavailable" on a video that really does have one.
        try:
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
            return [{"text": getattr(s, "text", "")} for s in fetched]
        except Exception:
            raise first_err  # the original error is the more informative one


def fetch_transcript_text(video_id):
    """Return (text, error) — exactly one of the two is set."""
    try:
        snippets = _fetch_raw_transcript(video_id)
    except Exception as e:
        print(f"[youtube] transcript fetch failed for {video_id}: {type(e).__name__}: {e}")
        name = type(e).__name__
        if "TranscriptsDisabled" in name:
            return None, "captions are disabled for this video"
        if "NoTranscriptFound" in name:
            return None, "no transcript/captions are available for this video"
        if "VideoUnavailable" in name:
            return None, "the video is unavailable (private, deleted, or region-locked)"
        if "IpBlocked" in name or "RequestBlocked" in name or "blocked" in str(e).lower():
            return None, ("YouTube is blocking transcript requests from this connection right now "
                          "(no proxy configured — see PROXY SUPPORT in agent/youtube.py)")
        if "TooManyRequests" in name or "429" in str(e):
            return None, "YouTube rate-limited this request — try again in a bit"
        return None, f"couldn't fetch a transcript ({e})"

    text = " ".join(s.get("text", "") for s in snippets if s.get("text")).strip()
    if not text:
        return None, "the transcript came back empty"
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = text[:_MAX_TRANSCRIPT_CHARS] + "\n…(transcript truncated for length)"
    return text, None


def youtube_context_block(message):
    """Scan `message` for YouTube links; return a text block with each
    video's transcript (or a clear per-video error note) to attach as
    context, or None if the message has no YouTube links at all."""
    ids = find_video_ids(message)
    if not ids:
        return None

    sections = []
    for vid in ids:
        text, err = fetch_transcript_text(vid)
        url = f"https://youtu.be/{vid}"
        if err:
            sections.append(
                f"[YouTube video {url}: transcript unavailable — {err}. "
                f"Tell the user this plainly; do not guess at or invent the video's content.]"
            )
        else:
            sections.append(f"[Transcript of YouTube video {url}]\n{text}")
    return "\n\n".join(sections)
