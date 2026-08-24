"""
parser.py — Format-adaptive log structure detector and deterministic parser.

Detects log patterns (JSON-lines, CSV, Key-Value, Space-Delimited, Bracketed)
and extracts structured events (timestamp, level, message) without hardcoded
schema assumptions.
"""

import csv
import json
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Regex Constants for Detection
# ---------------------------------------------------------------------------

# Timestamp Patterns
_TS_PATTERNS = [
    # Bracketed ISO 8601: [2026-08-22T14:22:45Z] or [2026-08-22 14:22:45]
    (re.compile(r"\[(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]"), "bracketed_iso"),
    # Standard ISO 8601 / Date-Time: 2026-08-22T14:22:45Z or 2026-08-22 14:22:45
    (re.compile(r"\b(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b"), "iso_dateTime"),
    # Common Slash Date-Time: 22/Aug/2026:14:22:45 or 2026/08/22 14:22:45
    (re.compile(r"\b(?P<ts>\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2})\b"), "slash_dateTime"),
    # Unix Epoch Timestamp (seconds/millis): e.g. 1787361765 or 1787361765.123
    (re.compile(r"\b(?P<ts>1\d{9}(?:\.\d+)?)\b"), "epoch"),
]

# Log Level Patterns
_LEVEL_RE = re.compile(
    r"\b(?:\[)?(?P<level>INFO|WARN|WARNING|ERROR|ERR|DEBUG|CRITICAL|FATAL|SEVERE)(?:\])?\b",
    re.IGNORECASE,
)


def _parse_ts_str(ts_str: str) -> datetime | None:
    """Best-effort parser for common timestamp string formats."""
    clean = ts_str.strip("[]\"'").replace("T", " ").rstrip("Z")
    
    # Safely strip ISO timezone offset (+05:00, -05:00, +0500) if present at end of string
    clean = re.sub(r"(?:[+-]\d{2}:?\d{2})$", "", clean).strip()

    # Truncate fractional seconds if present
    if "." in clean:
        parts = clean.split(".")
        clean = parts[0]

    clean = clean.strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Try epoch float
    try:
        val = float(clean)
        if val > 1e11:  # milliseconds
            val /= 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except ValueError:
        pass

    return None


def detect_log_structure(sample_lines: list[str]) -> dict:
    """
    Examine a sample of log lines to detect format structure.

    Returns dict:
    {
        "format": "json_lines" | "csv" | "key_value" | "space_delimited" | "unknown",
        "timestamp_pattern": str or None,
        "level_pattern": str or None,
        "delimiter": str or None,
        "json_keys": {"ts": ..., "level": ..., "msg": ...} (for json_lines),
        "csv_indices": {"ts": ..., "level": ..., "msg": ...} (for csv)
    }
    """
    lines = [l.strip() for l in sample_lines if l.strip()]
    if not lines:
        return {"format": "unknown"}

    # 1. Check if JSON-lines
    json_valid_count = 0
    detected_json_keys = {}
    for l in lines[:10]:
        if l.startswith("{") and l.endswith("}"):
            try:
                data = json.loads(l)
                if isinstance(data, dict):
                    json_valid_count += 1
                    for k in data.keys():
                        kl = k.lower()
                        if kl in ("timestamp", "time", "ts", "@timestamp", "date"):
                            detected_json_keys["ts"] = k
                        elif kl in ("level", "severity", "log_level", "lvl", "status"):
                            detected_json_keys["level"] = k
                        elif kl in ("message", "msg", "log", "text", "event", "detail"):
                            detected_json_keys["msg"] = k
            except Exception:
                pass

    if json_valid_count >= len(lines[:10]) * 0.7 and json_valid_count > 0:
        return {
            "format": "json_lines",
            "timestamp_pattern": "json",
            "level_pattern": "json",
            "delimiter": None,
            "json_keys": detected_json_keys,
        }

    # 2. Check if CSV format
    csv_count = 0
    csv_indices = {}
    for l in lines[:10]:
        if "," in l:
            parts = list(csv.reader([l]))[0]
            if len(parts) >= 3:
                csv_count += 1
                for idx, p in enumerate(parts):
                    p_str = p.strip()
                    if _parse_ts_str(p_str) is not None and "ts" not in csv_indices:
                        csv_indices["ts"] = idx
                    elif _LEVEL_RE.search(p_str) and "level" not in csv_indices:
                        csv_indices["level"] = idx

                if "msg" not in csv_indices and len(parts) > 2:
                    used = {csv_indices.get("ts"), csv_indices.get("level")}
                    for idx in range(len(parts)):
                        if idx not in used:
                            csv_indices["msg"] = idx
                            break

    if csv_count >= len(lines[:10]) * 0.7 and "ts" in csv_indices:
        return {
            "format": "csv",
            "timestamp_pattern": "csv",
            "level_pattern": "csv",
            "delimiter": ",",
            "csv_indices": csv_indices,
        }

    # 3. Check if Key-Value pairs (e.g. time=... level=... msg=...)
    kv_count = 0
    for l in lines[:10]:
        if len(re.findall(r"\b\w+=[^\s]+", l)) >= 2:
            kv_count += 1
    if kv_count >= len(lines[:10]) * 0.7:
        return {
            "format": "key_value",
            "timestamp_pattern": "kv",
            "level_pattern": "kv",
            "delimiter": " ",
        }

    # 4. Standard Delimited / Text Format Detection
    ts_found = False
    ts_pat_name = None
    level_found = False

    for l in lines[:10]:
        for pat, pat_name in _TS_PATTERNS:
            if pat.search(l):
                ts_found = True
                ts_pat_name = pat_name
                break
        if _LEVEL_RE.search(l):
            level_found = True

    if ts_found or level_found:
        return {
            "format": "space_delimited",
            "timestamp_pattern": ts_pat_name,
            "level_pattern": "level_regex",
            "delimiter": " ",
        }

    return {"format": "unknown"}


def parse_with_detected_structure(raw_log_text: str, structure: dict) -> list:
    """
    Parse raw log text using detected structure format.

    Returns list of dicts:
    [{"ts": datetime, "level": str, "message": str, "raw": str}, ...]
    """
    lines = [l.rstrip() for l in raw_log_text.splitlines() if l.strip()]
    results = []
    fmt = structure.get("format", "unknown")

    # --- Mode 1: JSON-lines ---
    if fmt == "json_lines":
        keys = structure.get("json_keys", {})
        ts_key = keys.get("ts", "ts")
        level_key = keys.get("level", "level")
        msg_key = keys.get("msg", "msg")

        for l in lines:
            try:
                data = json.loads(l)
                if not isinstance(data, dict):
                    continue

                ts_raw = str(data.get(ts_key) or data.get("timestamp") or data.get("time") or "")
                ts = _parse_ts_str(ts_raw) or datetime.now(tz=timezone.utc)

                lvl = str(data.get(level_key) or data.get("severity") or "INFO").upper()
                if lvl == "WARNING":
                    lvl = "WARN"
                elif lvl in ("CRITICAL", "FATAL", "SEVERE"):
                    lvl = "ERROR"

                msg = str(data.get(msg_key) or data.get("message") or data.get("log") or str(data))

                results.append({"ts": ts, "level": lvl, "message": msg, "raw": l})
            except Exception:
                pass
        return results

    # --- Mode 2: CSV ---
    if fmt == "csv":
        indices = structure.get("csv_indices", {})
        ts_idx = indices.get("ts", 0)
        lvl_idx = indices.get("level", 1)
        msg_idx = indices.get("msg", 2)

        for l in lines:
            try:
                parts = list(csv.reader([l]))[0]
                if len(parts) <= max(ts_idx, lvl_idx):
                    continue

                ts_str = parts[ts_idx].strip()
                ts = _parse_ts_str(ts_str) or datetime.now(tz=timezone.utc)

                lvl = parts[lvl_idx].strip().upper() if len(parts) > lvl_idx else "INFO"
                if lvl == "WARNING":
                    lvl = "WARN"
                elif lvl in ("CRITICAL", "FATAL", "SEVERE"):
                    lvl = "ERROR"
                elif not _LEVEL_RE.match(lvl):
                    lvl = "INFO"

                msg = parts[msg_idx].strip() if len(parts) > msg_idx else l
                results.append({"ts": ts, "level": lvl, "message": msg, "raw": l})
            except Exception:
                pass
        return results

    # --- Mode 3: Key-Value ---
    if fmt == "key_value":
        for l in lines:
            kv_pairs = dict(re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', l))
            kv_flat = {k: v1 or v2 for k, (v1, v2) in kv_pairs.items()}

            ts_raw = kv_flat.get("time") or kv_flat.get("ts") or kv_flat.get("timestamp") or ""
            ts = _parse_ts_str(ts_raw) or datetime.now(tz=timezone.utc)

            lvl = (kv_flat.get("level") or kv_flat.get("lvl") or "INFO").upper()
            if lvl == "WARNING":
                lvl = "WARN"
            elif lvl in ("CRITICAL", "FATAL", "SEVERE"):
                lvl = "ERROR"

            msg = kv_flat.get("msg") or kv_flat.get("message") or l
            results.append({"ts": ts, "level": lvl, "message": msg, "raw": l})
        return results

    # --- Mode 4: Delimited Text / Regex Slicing ---
    for l in lines:
        ts = None
        ts_match_end = 0

        for pat, _ in _TS_PATTERNS:
            m = pat.search(l)
            if m:
                ts = _parse_ts_str(m.group("ts"))
                ts_match_end = m.end()
                break

        if not ts:
            ts = datetime.now(tz=timezone.utc)

        level_m = _LEVEL_RE.search(l)
        if level_m:
            lvl = level_m.group("level").upper()
            if lvl == "WARNING":
                lvl = "WARN"
            elif lvl in ("CRITICAL", "FATAL", "SEVERE"):
                lvl = "ERROR"
            msg_start = max(ts_match_end, level_m.end())
            msg = l[msg_start:].strip(" :]-")
        else:
            lvl = "INFO"
            msg = l[ts_match_end:].strip(" :]-")

        if not msg:
            msg = l

        results.append({"ts": ts, "level": lvl, "message": msg, "raw": l})

    return results
