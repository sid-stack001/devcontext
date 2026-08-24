# DevContext

> **DevContext — an MCP server that gives coding agents live production context, so they diagnose incidents from evidence instead of guessing.**

---

## The Problem

Agentic coding assistants are code-aware but ops-blind. They can inspect a git repository and draft code fixes, but they lack visibility into what is actually occurring in runtime environments — such as recent deployments, error rate spikes, disk or connection pool exhaustion, or external dependency failures. As a result, agents often guess at root causes or propose superficial code changes instead of diagnosing incidents from concrete empirical evidence.

---

## Key Features

DevContext bridges runtime observability and AI coding agents by exposing four Model Context Protocol (MCP) tools:

- `get_recent_errors(service_name="", minutes=15, use_llm_extraction=False, log_path=None)` — Deterministic parser auto-detects common log structures (JSON-lines, CSV, key-value, bracketed ISO, delimited text) as a fast, dependency-free backbone. Optional LLM extraction (Groq) handles genuinely irregular or undocumented formats. Normalizes variable tokens (IDs, durations, quantities) into pattern templates (e.g. `#<N>`, `<N>ms`), aggregates counts, and flags severity spikes.
- `get_recent_deploys(service_name="", limit=5, deploys_path=None)` — Retrieves recent deployment history (commits, timestamps, authors, commit messages, and diff summaries), sorted newest-first from built-in data or a custom JSON file.
- `get_service_health(service_name="", health_path=None)` — Inspects live metric snapshots (CPU, memory, disk, active/max DB pool connections) and surfaces plain-English alert flags (e.g. *"Disk usage critical: 98%"*).
- `diagnose(service_name="", log_path=None, deploys_path=None, health_path=None)` — Synthesizes data across errors, deploys, and health metrics into a single grounded, plain-English `likely_cause` statement.

---

## Data Source Flexibility & Adaptive Parsing

DevContext supports two operating modes:

1. **Built-in Service Lookup**: Pass `service_name="order-processing"` (or any mock scenario name) to read from default `mock_data/` or scenario folders.
2. **Explicit File or Directory Paths**:
   - `log_path`: Pass an explicit single file path (e.g. `/var/log/my-app.log`) OR a directory path containing split/rotated `.log` / `.txt` files (e.g. `/var/log/nginx/`). DevContext automatically scans, sorts, and concatenates all log files in the directory.
   - **Format-Adaptive Deterministic Parsing (`parser.py`)**: DevContext automatically samples log lines to detect structural format (JSON-lines, CSV, key-value, bracketed ISO, or space-delimited text) and extracts timestamps, severity levels, and messages without requiring pre-configured log schemas.
   - `deploys_path`: Point to any custom deployment history JSON file.
   - `health_path`: Point to any live service health JSON metric endpoint or file.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                      MCP Clients                        │
│             (Claude Desktop / Antigravity)              │
└───────────────────────────┬─────────────────────────────┘
                            │ JSON-RPC (stdio)
┌───────────────────────────▼─────────────────────────────┐
│                 DevContext MCP Server                   │
│                       (server.py)                       │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                 Diagnostic Core (tools.py)               │
│        (Supports explicit log_path files & dirs)        │
└───────┬───────────────────┬─────────────────────┬───────┘
        │                   │                     │
┌───────▼───────────┐ ┌─────▼─────────────┐ ┌─────▼─────────────┐
│ Adaptive Parser   │ │ Deployment Engine │ │ Health Observer   │
│   (parser.py)     │ │ (deploys_path)    │ │ (health_path)     │
└───────┬───────────┘ └───────────────────┘ └───────────────────┘
        │
┌───────┴─────────────────────────────────────────┐
│  Groq API (Qwen 3.6 27B / Llama 3.1)            │
│  * (Optional LLM extraction layer for unparsed) │
└─────────────────────────────────────────────────┘
```

1. **Data Layer**: Supports built-in `mock_data/` files or explicit user-provided log files/directories and JSON endpoints.
2. **Adaptive Deterministic Parser**: `parser.py` inspects sample log lines, detects structural format (JSON-lines, CSV, KV, bracketed ISO), and parses timestamps/levels deterministically without external dependencies.
3. **Optional LLM Parser**: `extraction.py` uses Groq LLMs with structured JSON mode (`response_format={"type": "json_object"}`) to extract normalized event schemas from highly irregular or complex multi-line logs.
4. **Correlation Engine**: `diagnose()` evaluates temporal correlation between deploy timestamps and error spikes (10-minute window). If no deploy correlates, it evaluates system metrics (disk, memory/OOM) and external dependency patterns to avoid false deploy attribution.

---

## Evaluation & Accuracy Metrics

DevContext was evaluated against 5 synthetic incident scenarios representing distinct failure modes in modern cloud services:

| Scenario | Root Cause Type | Expected Behavior | Result | Note |
|---|---|---|---|---|
| `scenario_1_bad_deploy` | Resource Limit Reduction | Blame deploy `f8a1c92` | PASS | Correctly identified thread pool reduction deploy |
| `scenario_2_disk_full` | Disk Exhaustion | Do NOT blame deploy | PASS | Correctly attributed to 98% disk saturation (`Errno 28`) |
| `scenario_3_memory_leak` | Memory Leak / OOM | Do NOT blame deploy | PASS | Correctly attributed to gradual heap accumulation / OOM kill |
| `scenario_4_downstream_outage` | Downstream API Outage | Do NOT blame deploy | PASS | Correctly identified SendGrid `HTTP 503` external failure |
| `scenario_5_bad_migration` | Failed Schema Migration | Blame deploy `d4e912f` | PASS | Correctly identified migration failure and FK constraint error |

### Key Evaluation Highlights

- **Negative-Case Robustness**: 2 out of 5 scenarios (`scenario_2` & `scenario_3`) included a historical deploy in `deploys.json` that was not the cause of the outage. DevContext correctly avoided false attribution in both cases by verifying temporal correlation.
- **Overall Score**: **`5/5 (100%)` scenarios correctly diagnosed.**

> *Note*: The evaluation harness uses heuristic string matching against expected root-cause types. While effective for this benchmark suite, real-world deployment verification requires broader statistical confidence metrics.

---

## Incident Investigation Walkthrough

Below is a trace of an agent diagnosing `user-service` (`scenario_5_bad_migration`) using DevContext via Antigravity & Groq:

### 1. `get_service_health("user-service")`
```json
{
  "service": "user-service",
  "status": "degraded",
  "cpu_percent": 35.0,
  "memory_percent": 50.0,
  "disk_percent": 60,
  "active_db_connections": 5,
  "max_db_connections": 20,
  "flags": ["Service status: degraded"]
}
```

### 2. `get_recent_errors("user-service", use_llm_extraction=True)`
```json
{
  "total_flagged_lines": 4,
  "first_error_timestamp": "2026-08-22T16:00:05+00:00",
  "error_summary": {
    "Query failed for user #<N>: relation \"user_preferences\" does not exist": { "count": 1, "level": "ERROR" },
    "Column \"user_id\" in field list is ambiguous during SQL JOIN query": { "count": 1, "level": "ERROR" },
    "Database migration failure: foreign key constraint violation on user_preferences_fk": { "count": 1, "level": "ERROR" }
  }
}
```

### 3. `get_recent_deploys("user-service")`
```json
{
  "deploys": [
    {
      "commit": "d4e912f",
      "timestamp": "2026-08-22T16:00:00+00:00",
      "author": "db-admin",
      "message": "Apply schema migration: add user_preferences table & constraints",
      "diff_summary": "migrations/V4__user_preferences.sql: create table user_preferences, add FK constraint to users"
    }
  ]
}
```

### Grounded Diagnosis & Action Plan
- **Root Cause**: Deploy `d4e912f` at `16:00:00` (5 seconds before the first error) executed `V4__user_preferences.sql`, which failed mid-migration due to a foreign key constraint violation (`user_preferences_fk`).
- **Remediation**: Revert migration script `V4__user_preferences.sql`, drop transient tables via `DROP TABLE IF EXISTS user_preferences CASCADE;`, and resolve foreign key constraints before re-deploying.

---

## Quickstart & Setup

### 1. Installation
```bash
git clone https://github.com/your-username/devcontext.git
cd devcontext
pip install -r requirements.txt
```

### 2. Run Standalone
```bash
python server.py
```
*(Runs stdio transport server waiting for MCP JSON-RPC protocol messages)*

### 3. Register with Claude Desktop / MCP Clients
Add DevContext to your `claude_desktop_config.json`:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "devcontext": {
      "command": "python",
      "args": [
        "C:\\path\\to\\devcontext\\server.py"
      ]
    }
  }
}
```

### 4. Custom Log File or Directory Usage
Agents can point directly to custom log files or directory folders:
```python
# Pass a single file path or folder
get_recent_errors(log_path="/var/log/my-service.log")

# Adaptive deterministic parser auto-detects JSON-lines, CSV, Key-Value, or Delimited text
get_recent_errors(log_path="/var/log/app_cluster/")
```

### 5. Optional: Groq LLM Event Extraction
Set `GROQ_API_KEY` to enable Groq LLM log parsing:
```bash
export GROQ_API_KEY="gsk_..."
```
*(If omitted, DevContext automatically uses its format-adaptive deterministic parser with zero degradation)*

---

## Tech Stack

- **Language**: Python 3.10+
- **Protocol**: Model Context Protocol (MCP) SDK (`mcp`)
- **LLM Infrastructure**: Groq SDK (`groq`)
- **Clients Supported**: Claude Desktop, Antigravity IDE, Cursor, or any stdio MCP host

---

## License

Distributed under the [MIT License](LICENSE).
