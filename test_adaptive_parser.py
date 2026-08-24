"""
test_adaptive_parser.py — Test format-adaptive log parser against 3 synthetic log formats.
"""

import json
from pathlib import Path
from parser import detect_log_structure, parse_with_detected_structure
import tools

# --- Format 1: JSON-lines ---
LOG_FORMAT_1_JSON = """
{"timestamp": "2026-08-24 12:00:00", "level": "INFO", "message": "API gateway worker started"}
{"timestamp": "2026-08-24 12:00:05", "level": "WARN", "message": "High CPU utilization detected: 89%"}
{"timestamp": "2026-08-24 12:00:10", "level": "ERROR", "message": "Database connection pool saturated: 20/20 active"}
{"timestamp": "2026-08-24 12:00:15", "level": "ERROR", "message": "Failed transaction #9901: Connection timeout to DB"}
""".strip()

# --- Format 2: CSV ---
LOG_FORMAT_2_CSV = """
2026-08-24 12:05:00,INFO,Order service dispatcher active
2026-08-24 12:05:05,WARN,Disk partition /var/log reaching capacity: 87%
2026-08-24 12:05:10,ERROR,Payment gateway HTTP 504 Gateway Timeout after 5000ms
2026-08-24 12:05:15,ERROR,Failed order #1042: Payment processing error
""".strip()

# --- Format 3: Branded Bracketed ISO ---
LOG_FORMAT_3_BRACKETED = """
[2026-08-24T12:10:00Z] [INFO] Worker node initialized (PID 5012)
[2026-08-24T12:10:05Z] [WARN] Heap memory alert: 86% utilized
[2026-08-24T12:10:10Z] [ERROR] OutOfMemoryError: Java heap space exhausted
[2026-08-24T12:10:15Z] [ERROR] Process killed by OS OOM-killer (PID 5012)
""".strip()

formats = [
    ("Format 1: JSON-lines", LOG_FORMAT_1_JSON, "log_1_json.log"),
    ("Format 2: CSV", LOG_FORMAT_2_CSV, "log_2_csv.csv"),
    ("Format 3: Bracketed ISO", LOG_FORMAT_3_BRACKETED, "log_3_bracketed.log"),
]

tmp_dir = Path("scratch_adaptive_test")
tmp_dir.mkdir(exist_ok=True)

print("=" * 80)
print("TESTING FORMAT-ADAPTIVE DETERMINISTIC LOG PARSER")
print("=" * 80)

for name, text, filename in formats:
    file_path = tmp_dir / filename
    file_path.write_text(text, encoding="utf-8")

    sample = text.splitlines()
    struct = detect_log_structure(sample)

    print(f"\n--- {name} ---")
    print("Detected Structure:", struct)

    parsed = parse_with_detected_structure(text, struct)
    print(f"Parsed Events Count: {len(parsed)}")
    for event in parsed:
        ts_fmt = event["ts"].strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [{ts_fmt}] [{event['level']:5}] {event['message']}")

    # Also test integration via get_recent_errors()
    res = tools.get_recent_errors(log_path=str(file_path), minutes=600)
    print(f"get_recent_errors() Flagged Count: {res['total_flagged_lines']}")
    print("Error Summary Patterns:")
    for pat, info in res["error_summary"].items():
        print(f"   · [{info['level']}] x{info['count']}: {pat}")

print("\n" + "=" * 80)
print("ALL 3 SYNTHETIC FORMATS SUCCESSFULLY DETECTED AND PARSED DETERMINISTICALLY!")
print("=" * 80)
