"""
test_extraction.py — Test script and latency benchmark for extraction.py
"""

import json
import os
import time
from pathlib import Path

from extraction import _regex_fallback, extract_events

_HERE = Path(__file__).parent

# Load scenario log files
p_disk = _HERE / "eval_scenarios" / "scenario_2_disk_full" / "storage-service.log"
p_mem = _HERE / "eval_scenarios" / "scenario_3_memory_leak" / "analytics-worker.log"

log_disk = p_disk.read_text(encoding="utf-8")
log_mem = p_mem.read_text(encoding="utf-8")

print("=" * 75)
print("GROQ API KEY STATUS:", "PRESENT" if os.getenv("GROQ_API_KEY") else "MISSING (Fallback active)")
print("=" * 75)

# --- Benchmark & Extract Scenario 2: Disk Full ---
print("\n--- [Scenario 2: Disk Full (storage-service)] ---")
t0 = time.perf_counter()
regex_disk_events = _regex_fallback(log_disk, "storage-service")
t_regex_disk = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
groq_disk_events = extract_events(log_disk, "storage-service")
t_groq_disk = (time.perf_counter() - t0) * 1000

print(f"Regex Parser Latency: {t_regex_disk:.2f} ms ({len(regex_disk_events)} events)")
print(f"Groq Extraction Latency: {t_groq_disk:.2f} ms ({len(groq_disk_events)} events)")
print("\nExtracted Events (Groq/LLM output):")
print(json.dumps(groq_disk_events, indent=2))

# --- Benchmark & Extract Scenario 3: Memory Leak ---
print("\n" + "=" * 75)
print("--- [Scenario 3: Memory Leak (analytics-worker)] ---")
t0 = time.perf_counter()
regex_mem_events = _regex_fallback(log_mem, "analytics-worker")
t_regex_mem = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
groq_mem_events = extract_events(log_mem, "analytics-worker")
t_groq_mem = (time.perf_counter() - t0) * 1000

print(f"Regex Parser Latency: {t_regex_mem:.2f} ms ({len(regex_mem_events)} events)")
print(f"Groq Extraction Latency: {t_groq_mem:.2f} ms ({len(groq_mem_events)} events)")
print("\nExtracted Events (Groq/LLM output):")
print(json.dumps(groq_mem_events, indent=2))

print("\n" + "=" * 75)
print("LATENCY COMPARISON SUMMARY")
print("=" * 75)
print(f"Scenario 2 (Disk Full)   : Regex = {t_regex_disk:.2f} ms | Groq = {t_groq_disk:.2f} ms")
print(f"Scenario 3 (Memory Leak): Regex = {t_regex_mem:.2f} ms | Groq = {t_groq_mem:.2f} ms")
print("=" * 75)
