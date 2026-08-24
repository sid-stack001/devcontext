# DevContext

> **DevContext is a prototype Model Context Protocol (MCP) server and CLI tool that provides AI coding assistants and engineers with runtime observability data (logs, deploys, and health metrics) to assist in incident triage.**

---

## Overview

Coding assistants can inspect source repositories and draft fixes, but they often lack visibility into what happens during runtime incidents (such as recent deployments, error rate spikes, disk saturation, or downstream API outages). DevContext is a proof-of-concept tool that exposes runtime context via a command-line interface (CLI) and standard MCP tool calls.

---

## CLI & Tool Commands

DevContext can be run directly from the command line or registered as an MCP server.

### 1. `devcontext diagnose`
Runs automated incident triage against built-in datasets or custom files/folders:
```bash
# Diagnose built-in service dataset
devcontext diagnose --service order-processing

# Output raw JSON format
devcontext diagnose --service order-processing --json

# Point at custom log, deploy, and health paths (files or log directories)
devcontext diagnose --log-path /var/log/app/ --deploys-path deploys.json --health-path health.json

# Enable experimental Groq LLM extraction
devcontext diagnose --service order-processing --use-llm
```

### 2. `devcontext serve`
Starts the stdio MCP server for connection to MCP hosts (e.g. Claude Desktop, Antigravity):
```bash
devcontext serve
```

---

## Log Parsing Options

1. **Deterministic Parser (`parser.py`)**: Uses heuristics to sample log lines and attempt structure matching (JSON-lines, CSV, key-value pairs, or basic bracketed/space-delimited timestamps).
   - *Limitation*: Best suited for simple single-line logs. Complex multi-line stack traces or non-standard custom formats may fall back to basic line matching.
2. **Experimental LLM Extraction (`extraction.py`)**: Optionally sends log chunks to Groq's API (`response_format={"type": "json_object"}`) to extract structured event objects.
   - *Limitation*: Incurs API latency (~200–400ms) and token costs; falls back to the deterministic parser if the API key is missing or calls time out.

---

## Data Source Options

- **Built-in Mock Data**: Pass a service name (e.g. `service_name="order-processing"`) to query the included demo data.
- **Custom File or Directory Paths**:
  - `log_path`: Path to a single log file or a directory containing split `.log` / `.txt` files.
  - `deploys_path`: Path to a custom `deploys.json` file.
  - `health_path`: Path to a custom `health.json` file.

---

## Evaluation & Test Scenarios

The repository includes an evaluation harness (`eval.py`) tested against 5 synthetic test scenarios:

| Scenario | Service | Scenario Type | Expected Outcome | Result |
|---|---|---|---|---|
| `scenario_1_bad_deploy` | `payment-service` | Resource Limit Reduction | Identify deploy `f8a1c92` | Pass |
| `scenario_2_disk_full` | `storage-service` | Disk Full (No recent deploy) | Identify disk exhaustion (98%) | Pass |
| `scenario_3_memory_leak` | `analytics-worker` | Memory Leak / OOM | Identify memory saturation (97%) | Pass |
| `scenario_4_downstream_outage` | `notification-service` | External API Outage | Identify SendGrid 503 errors | Pass |
| `scenario_5_bad_migration` | `user-service` | Failed Database Migration | Identify deploy `d4e912f` | Pass |

### Limitations & Scope
- **Small Test Suite**: This evaluation suite contains 5 synthetic test cases created for validation. It is not an exhaustive production benchmark.
- **Heuristic Matching**: `diagnose()` uses simple rules (e.g. checking if a deploy occurred within 10 minutes of the first error). Real-world infrastructure incidents are often more complex and may involve multiple interacting factors.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│              CLI / MCP Clients                          │
│     (devcontext CLI / Claude Desktop / Antigravity)     │
└───────────────────────────┬─────────────────────────────┘
                            │ CLI Args / stdio JSON-RPC
┌───────────────────────────▼─────────────────────────────┐
│              DevContext Entry Point                     │
│               (cli.py / server.py)                      │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                 Diagnostic Core (tools.py)               │
└───────┬───────────────────┬─────────────────────┬───────┘
        │                   │                     │
┌───────▼───────────┐ ┌─────▼─────────────┐ ┌─────▼─────────────┐
│ Structure Parser  │ │ Deployment Engine │ │ Health Observer   │
│   (parser.py)     │ │ (deploys.json)    │ │ (health.json)     │
└───────┬───────────┘ └───────────────────┘ └───────────────────┘
        │
┌───────┴─────────────────────────────────────────┐
│  Groq API (Optional LLM log extraction)         │
└─────────────────────────────────────────────────┘
```

---

## Quickstart & Setup

### 1. Installation
```bash
git clone https://github.com/your-username/devcontext.git
cd devcontext
pip install -e .
```

### 2. Diagnose a Service via CLI
```bash
devcontext diagnose --service order-processing
```

### 3. Register as an MCP Server (Claude Desktop)
Add DevContext to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "devcontext": {
      "command": "devcontext",
      "args": [
        "serve"
      ]
    }
  }
}
```

### 4. Run Evaluation Suite
```bash
python eval.py
```

### 5. Optional API Key Setup
Copy `.env.example` to `.env` if using Groq for experimental LLM log extraction:
```bash
cp .env.example .env
```

---

## Dependencies & Requirements

- Python 3.10+
- `mcp` (Model Context Protocol SDK)
- `groq` (Optional, for LLM extraction)

---

## License

Distributed under the [MIT License](LICENSE).
