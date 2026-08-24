"""
extraction.py — LLM-based log event extraction using Groq API.

Provides extract_events(), which sends raw log text to Groq's chat completions
API (with response_format={"type": "json_object"}) and parses the response into
normalised event dicts.

Falls back automatically to the built-in regex parser if:
  - GROQ_API_KEY environment variable is not set
  - The API call fails or JSON response is malformed
  - Any unexpected exception occurs

Usage:
    from extraction import extract_events
    events = extract_events(raw_log_text, "storage-service")

Requires:
    pip install groq
"""

import json
import os
import re
import time

try:
    from groq import Groq
except ImportError:
    Groq = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("GROQ_API_KEY")
_MODEL_NAME = "qwen/qwen3.6-27b"

_EXTRACTION_PROMPT_TEMPLATE = """\
You are a log analysis assistant. Parse the following service log lines for service "{service_name}" and extract structured events.

Return a JSON object containing a top-level key "events" which is an array of objects.
For EACH log line, the event object MUST have these exact fields:
- "timestamp": the timestamp string exactly as written (format: YYYY-MM-DD HH:MM:SS)
- "level": one of "INFO", "WARN", "ERROR", "DEBUG"
- "message_raw": the message text after the level/bracket, exactly as written
- "message_normalized": the same message but with ALL variable parts replaced:
    · numbers / quantities / IDs → <N> (e.g. "#88412" -> "#<N>", "3000ms" -> "<N>ms", "92%" -> "<N>%")
    · hex strings / hashes → <HASH>
    · IP addresses → <IP>
    · UUIDs → <UUID>
- "metrics": a JSON object of any embedded key=value numbers

Rules:
- Output MUST be a valid JSON object with key "events".
- Extract every log line present. Do not skip lines.

Log lines for service "{service_name}":
---
{log_lines}
---
"""

# ---------------------------------------------------------------------------
# Regex-based fallback
# ---------------------------------------------------------------------------

_FALLBACK_NORMALISE = [
    (re.compile(r"#\d+"), "#<N>"),
    (re.compile(r"\b\d+ms\b"), "<N>ms"),
    (re.compile(r"\b\d+/\d+\b"), "<N>/<N>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]

_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"\s+(?:\[(?P<level1>INFO|WARN|ERROR|DEBUG|CRITICAL|WARNING|FATAL)\]|(?P<level2>INFO|WARN|ERROR|DEBUG|CRITICAL|WARNING|FATAL))"
    r"\s*(?:\[(?P<service>[^\]]+)\])?"
    r"\s*(?P<message>.+)$",
    re.IGNORECASE,
)


def _regex_fallback(raw_log_text: str, service_name: str) -> list:
    """Regex-based parser used when Groq LLM extraction is unavailable."""
    results = []
    for raw in raw_log_text.splitlines():
        if not raw.strip():
            continue
        m = _LOG_LINE_RE.match(raw.strip())
        if not m:
            # Fallback line extraction for non-standard lines
            results.append(
                {
                    "timestamp": "2026-08-24 00:00:00",
                    "level": "ERROR" if "error" in raw.lower() or "fail" in raw.lower() else ("WARN" if "warn" in raw.lower() else "INFO"),
                    "message_raw": raw.strip(),
                    "message_normalized": raw.strip(),
                    "metrics": {},
                }
            )
            continue

        msg = m.group("message")
        normalized = msg
        for pat, repl in _FALLBACK_NORMALISE:
            normalized = pat.sub(repl, normalized)
        metrics = {}
        for kv in re.finditer(r"(\w+)=(\d+(?:\.\d+)?)", msg):
            try:
                metrics[kv.group(1)] = float(kv.group(2))
            except ValueError:
                pass

        lvl = (m.group("level1") or m.group("level2") or "INFO").upper()
        if lvl == "WARNING":
            lvl = "WARN"
        elif lvl in ("CRITICAL", "FATAL"):
            lvl = "ERROR"

        results.append(
            {
                "timestamp": m.group("ts").replace("T", " "),
                "level": lvl,
                "message_raw": msg,
                "message_normalized": normalized,
                "metrics": metrics,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_events(raw_log_text: str, service_name: str) -> list:
    """
    Use Groq's LLM API to parse arbitrary log formats into a normalized structure.

    Falls back to regex parser if:
        - GROQ_API_KEY environment variable is missing
        - groq package is not installed
        - API call fails or returns malformed JSON
    """
    api_key = os.getenv("GROQ_API_KEY") or _API_KEY
    if not api_key or Groq is None:
        return _regex_fallback(raw_log_text, service_name)

    try:
        client = Groq(api_key=api_key)
        prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
            service_name=service_name,
            log_lines=raw_log_text,
        )

        response = client.chat.completions.create(
            model=_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise log parsing assistant that outputs strict JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content
        parsed = json.loads(content)
        events = parsed.get("events") if isinstance(parsed, dict) else parsed
        if isinstance(events, list) and events:
            return events
    except Exception:
        pass

    return _regex_fallback(raw_log_text, service_name)
