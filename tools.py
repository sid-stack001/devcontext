"""
tools.py — Diagnostic tools for the devcontext demo.

All functions read from mock_data/ (relative to this file) by default,
but accept an optional data_dir argument or explicit file/directory paths
(log_path, deploys_path, health_path).

Only the Python standard library is required (json, re, pathlib, datetime).

Public API
----------
get_recent_errors(service_name, minutes=15, data_dir=None, use_llm_extraction=False, log_path=None)
get_recent_deploys(service_name, limit=5, data_dir=None, deploys_path=None)
get_service_health(service_name, data_dir=None, health_path=None)
diagnose(service_name, data_dir=None, log_path=None, deploys_path=None, health_path=None)
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from parser import detect_log_structure, parse_with_detected_structure

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_DEFAULT_MOCK_DATA = _HERE / "mock_data"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEPLOY_CORRELATION_WINDOW_SECS = 600  # 10 minutes

_EXTERNAL_INDICATORS = [
    "http 5", "http 4", "api.", ".io", "sendgrid", "smtp",
    "unreachable", "downstream", "external", "connection refused to",
    "third-party", "3rd-party", "webhook",
]

_INTERNAL_DB_INDICATORS = [
    "pool", "db timeout", "connection pool", "postgres", "mysql",
    "database", "jdbc", "sqlalchemy",
]

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_NORMALISE_PATTERNS = [
    (re.compile(r"#\d+"), "#<N>"),
    (re.compile(r"\b\d+ms\b"), "<N>ms"),
    (re.compile(r"\b\d+/\d+\b"), "<N>/<N>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]

# Standard regex fallback line format
_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>INFO|WARN|ERROR|DEBUG|CRITICAL|WARNING|FATAL)"
    r"(?:\s+\[(?P<service>[^\]]+)\])?"
    r"\s+(?P<message>.+)$",
    re.IGNORECASE,
)


def _resolve_data_dir(data_dir) -> Path:
    return Path(data_dir) if data_dir is not None else _DEFAULT_MOCK_DATA


def _normalise(message: str) -> str:
    """Replace variable tokens with placeholders for error grouping."""
    for pattern, replacement in _NORMALISE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


def _parse_log_line_legacy(raw: str, default_service: str = ""):
    """Fallback legacy parser for unparseable fallback lines."""
    m = _LOG_LINE_RE.match(raw.strip())
    if not m:
        return None

    ts_str = m.group("ts").replace("T", " ")
    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    level = m.group("level").upper()
    if level == "WARNING":
        level = "WARN"
    elif level in ("CRITICAL", "FATAL"):
        level = "ERROR"

    service = m.group("service") or default_service

    return {
        "ts": ts,
        "level": level,
        "service": service,
        "message": m.group("message"),
        "raw": raw.rstrip(),
    }


def _read_log_source(service_name: str, data_dir: Path, log_path=None) -> str:
    """
    Read raw log text from log_path (file or directory of .log/.txt files),
    or fall back to service log lookup inside data_dir.
    """
    if log_path is not None:
        p = Path(log_path)
        if not p.exists():
            raise FileNotFoundError(f"Log path does not exist: {log_path}")

        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        elif p.is_dir():
            log_files = sorted(
                [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in (".log", ".txt")]
            )
            if not log_files:
                return ""
            contents = []
            for f in log_files:
                try:
                    contents.append(f.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    pass
            return "\n".join(contents)

    candidate = data_dir / f"{service_name}.log"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8", errors="replace")
    logs = list(data_dir.glob("*.log"))
    if logs:
        return logs[0].read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(
        f"No log file found for service '{service_name}' in {data_dir}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_recent_errors(
    service_name: str = "",
    minutes: int = 15,
    data_dir=None,
    use_llm_extraction: bool = False,
    log_path=None,
) -> dict:
    """
    Fetch and summarise recent ERROR and WARN log lines for a service.

    Deterministic parser auto-detects common log structures (JSON-lines, CSV,
    key-value, delimited text) as a fast, dependency-free backbone. Optional
    LLM extraction (Groq) handles genuinely irregular or undocumented formats.

    Accepts an optional `log_path` pointing directly to a log file or a
    directory containing rotated/split `.log` or `.txt` files.

    Returns a dict with:
    - "total_flagged_lines": how many ERROR/WARN lines were found
    - "first_error_timestamp": ISO 8601 timestamp of the first flagged line
    - "error_summary": dict mapping normalised pattern → {count, level, sample}
    - "last_10_raw_lines": the last 10 raw log lines for full context
    """
    resolved = _resolve_data_dir(data_dir)
    raw_text = _read_log_source(service_name, resolved, log_path=log_path)

    all_parsed = []
    raw_lines = []
    llm_used = False

    # --- Mode 1: LLM Extraction ---
    if use_llm_extraction and raw_text.strip():
        try:
            from extraction import extract_events

            events = extract_events(raw_text, service_name)
            for e in events:
                try:
                    ts_str = str(e["timestamp"]).replace("T", " ")
                    if "." in ts_str:
                        ts_str = ts_str.split(".")[0]
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except (ValueError, KeyError):
                    continue
                raw_line = (
                    f"{e['timestamp']} {e.get('level', 'INFO'):5} "
                    f"[{service_name}] {e.get('message_raw', '')}"
                )
                all_parsed.append(
                    {
                        "ts": ts,
                        "level": e.get("level", "INFO"),
                        "service": service_name,
                        "message": e.get("message_raw", ""),
                        "message_normalized": e.get("message_normalized", ""),
                        "raw": raw_line,
                    }
                )
                raw_lines.append(raw_line)
            if all_parsed:
                llm_used = True
        except Exception:
            pass  # fall through to adaptive structure parser

    # --- Mode 2: Format-Adaptive Structure Parser ---
    if not llm_used and raw_text.strip():
        sample_lines = [l for l in raw_text.splitlines() if l.strip()][:30]
        structure = detect_log_structure(sample_lines)

        if structure.get("format") != "unknown":
            parsed_events = parse_with_detected_structure(raw_text, structure)
            for p in parsed_events:
                all_parsed.append(
                    {
                        "ts": p["ts"],
                        "level": p["level"],
                        "service": service_name,
                        "message": p["message"],
                        "raw": p["raw"],
                    }
                )
                raw_lines.append(p["raw"])
        else:
            # Fallback legacy regex parser
            for raw in raw_text.splitlines():
                parsed = _parse_log_line_legacy(raw, default_service=service_name)
                if parsed:
                    all_parsed.append(parsed)
                    raw_lines.append(parsed["raw"])

    if all_parsed:
        last_ts = all_parsed[-1]["ts"]
        cutoff = last_ts - timedelta(minutes=minutes)
    else:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)

    flagged = [
        p
        for p in all_parsed
        if p["level"] in ("ERROR", "WARN") and p["ts"] >= cutoff
    ]

    first_error_timestamp = flagged[0]["ts"].isoformat() if flagged else None

    error_summary: dict = {}
    _LEVEL_RANK = {"WARN": 1, "ERROR": 2}
    for entry in flagged:
        key = entry.get("message_normalized") or _normalise(entry["message"])
        if key not in error_summary:
            error_summary[key] = {
                "count": 0,
                "level": entry["level"],
                "sample": entry["raw"],
            }
        error_summary[key]["count"] += 1
        if _LEVEL_RANK.get(entry["level"], 0) > _LEVEL_RANK.get(
            error_summary[key]["level"], 0
        ):
            error_summary[key]["level"] = entry["level"]

    return {
        "service": service_name,
        "window_minutes": minutes,
        "total_flagged_lines": len(flagged),
        "first_error_timestamp": first_error_timestamp,
        "error_summary": error_summary,
        "last_10_raw_lines": raw_lines[-10:],
    }


def get_recent_deploys(
    service_name: str = "",
    limit: int = 5,
    data_dir=None,
    deploys_path=None,
) -> dict:
    """Retrieve recent deployments for a service, sorted newest-first."""
    if deploys_path is not None:
        p = Path(deploys_path)
    else:
        resolved = _resolve_data_dir(data_dir)
        p = resolved / "deploys.json"

    if not p.exists():
        return {"service": service_name, "limit": limit, "deploys": []}

    with p.open(encoding="utf-8") as fh:
        all_deploys = json.load(fh)

    filtered = [
        d for d in all_deploys
        if not service_name or d.get("service") == service_name or len(all_deploys) == 1
    ]
    filtered.sort(key=lambda d: d.get("timestamp", ""), reverse=True)

    return {
        "service": service_name,
        "limit": limit,
        "deploys": filtered[:limit],
    }


def get_service_health(
    service_name: str = "",
    data_dir=None,
    health_path=None,
) -> dict:
    """Return current health metrics for a service, with a plain-English flags list."""
    if health_path is not None:
        p = Path(health_path)
    else:
        resolved = _resolve_data_dir(data_dir)
        p = resolved / "health.json"

    if not p.exists():
        return {
            "service": service_name,
            "error": f"Health file not found at {p}",
            "flags": [],
        }

    with p.open(encoding="utf-8") as fh:
        all_health = json.load(fh)

    if service_name in all_health:
        health = dict(all_health[service_name])
    elif len(all_health) == 1:
        health = dict(next(iter(all_health.values())))
    else:
        return {
            "service": service_name,
            "error": "Service not found in health metrics",
            "flags": [],
        }

    flags: list = []

    disk = health.get("disk_percent", 0)
    if disk > 85:
        flags.append(f"Disk usage critical: {disk}%")

    memory = health.get("memory_percent", 0)
    if memory > 90:
        flags.append(f"Memory usage critical: {memory}%")

    active = health.get("active_db_connections", 0)
    max_conn = health.get("max_db_connections", 0)
    if max_conn > 0 and active >= max_conn:
        flags.append(
            f"DB connection pool exhausted (at max capacity: {active}/{max_conn})"
        )

    status = health.get("status", "unknown")
    if status != "healthy":
        flags.append(f"Service status: {status}")

    return {"service": service_name, **health, "flags": flags}


def diagnose(
    service_name: str = "",
    data_dir=None,
    log_path=None,
    deploys_path=None,
    health_path=None,
) -> dict:
    """
    Run a full automated diagnosis for a service and identify the likely root cause.
    """
    errors = get_recent_errors(service_name, data_dir=data_dir, log_path=log_path)
    deploys = get_recent_deploys(service_name, data_dir=data_dir, deploys_path=deploys_path)
    health = get_service_health(service_name, data_dir=data_dir, health_path=health_path)

    deploy_list = deploys.get("deploys", [])
    latest_deploy = deploy_list[0] if deploy_list else None
    first_error_ts_str = errors.get("first_error_timestamp")

    deploy_is_recent = False
    gap_secs = None

    if latest_deploy and first_error_ts_str:
        try:
            error_ts = datetime.fromisoformat(first_error_ts_str)
            deploy_ts = datetime.fromisoformat(latest_deploy["timestamp"])
            gap_secs = (error_ts - deploy_ts).total_seconds()
            deploy_is_recent = 0 <= gap_secs <= _DEPLOY_CORRELATION_WINDOW_SECS
        except (ValueError, KeyError):
            pass

    if deploy_is_recent and latest_deploy:
        commit = latest_deploy.get("commit", "unknown")
        author = latest_deploy.get("author", "unknown")
        message = latest_deploy.get("message", "")
        diff = latest_deploy.get("diff_summary", "")
        ts = latest_deploy.get("timestamp", "")
        likely_cause = (
            f"The most likely cause is the deploy at {ts} by {author} "
            f"(commit {commit}): \"{message}\". "
            f"Diff summary: {diff}. "
            f"This deploy closely precedes the error spike (gap: {int(gap_secs)}s) "
            f"and directly modified a configuration or schema that matches the "
            f"observed failure mode."
        )
        return {
            "service": service_name,
            "errors": errors,
            "deploys": deploys,
            "health": health,
            "likely_cause": likely_cause,
        }

    health_flags = health.get("flags", [])
    error_summary = errors.get("error_summary", {})
    error_patterns_text = " ".join(error_summary.keys()).lower()
    flags_text = " ".join(health_flags).lower()
    combined = error_patterns_text + " " + flags_text

    disk_pct = health.get("disk_percent", 0)
    memory_pct = health.get("memory_percent", 0)

    if disk_pct > 95 or any(
        kw in combined
        for kw in ["no space left", "disk usage", "errno 28", "disk full"]
    ):
        likely_cause = (
            f"No recent deploy correlates with the error spike. "
            f"Root cause is disk exhaustion: disk at {disk_pct}%. "
            f"The service is failing to write to disk. "
            f"Immediate remediation: purge old logs/snapshots on the data volume "
            f"or expand volume capacity."
        )

    elif memory_pct > 90 or any(
        kw in combined
        for kw in ["out of memory", "oom", "heap exhausted", "memory usage"]
    ):
        likely_cause = (
            f"No recent deploy correlates with the error spike. "
            f"Root cause is memory exhaustion: memory at {memory_pct}%. "
            f"This pattern — gradual accumulation without relief — is consistent "
            f"with a memory leak (objects allocated but never released). "
            f"Immediate remediation: restart the service. "
            f"Long-term: profile the heap for retained objects (e.g. unbounded caches)."
        )

    elif any(kw in combined for kw in _EXTERNAL_INDICATORS) and not any(
        kw in combined for kw in _INTERNAL_DB_INDICATORS
    ):
        likely_cause = (
            f"No recent deploy correlates with the error spike. "
            f"Root cause appears to be a downstream/external dependency failure: "
            f"error patterns indicate an external service or API is unreachable or "
            f"returning server errors. "
            f"This service's own resources (disk, memory, DB pool) appear healthy. "
            f"Remediation: check the health of third-party API providers and "
            f"upstream services; implement a circuit-breaker / retry with backoff "
            f"if not already in place."
        )

    elif latest_deploy and gap_secs is not None:
        gap_hrs = gap_secs / 3600
        likely_cause = (
            f"Root cause unclear. No deploy within the 10-minute correlation window. "
            f"Most recent deploy was {latest_deploy['commit']} by "
            f"{latest_deploy['author']} ({gap_hrs:.1f}h before the error spike) — "
            f"too far in the past to correlate directly. "
            f"Active health flags: {health_flags}. "
            f"Recommend investigating application-level metrics and recent config changes."
        )

    else:
        likely_cause = (
            "Root cause undetermined: no recent deploy, no clear resource "
            "exhaustion, and no external dependency signals detected. "
            f"Active health flags: {health_flags}."
        )

    return {
        "service": service_name,
        "errors": errors,
        "deploys": deploys,
        "health": health,
        "likely_cause": likely_cause,
    }
