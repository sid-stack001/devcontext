"""
server.py — MCP server for the devcontext diagnostic toolkit.

Exposes four tools that an AI agent can call to diagnose incidents for
any service (either using built-in demo data or explicit file/directory paths).

Run standalone (stdio transport):
    python server.py

Register with an MCP client (e.g. Claude Desktop) via claude_desktop_config.json.
"""

from mcp.server.mcpserver.server import MCPServer

import tools

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = MCPServer("devcontext")

# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


@mcp.tool()
def get_recent_errors(
    service_name: str = "",
    minutes: int = 15,
    use_llm_extraction: bool = False,
    log_path: str | None = None,
) -> dict:
    """
    Fetch and summarise recent ERROR and WARN log lines for a service.

    Accepts an optional `log_path` parameter pointing directly to a log file or to a
    directory containing multiple `.log` / `.txt` files (which will be read and
    concatenated). If `log_path` is not provided, it falls back to looking up
    `mock_data/<service_name>.log`.

    If `use_llm_extraction=True` is passed, it uses Groq Llama 3.1 8B Instant
    (via extraction.py) to parse arbitrary/unstructured log formats into JSON.

    Args:
        service_name: Service name (e.g. "order-processing" or "payment-service").
        minutes: Time window in minutes to filter error lines (default 15).
        use_llm_extraction: Set to True to use LLM extraction for unfamiliar log formats.
        log_path: Optional path to a specific log file or folder of .log/.txt files.
    """
    return tools.get_recent_errors(
        service_name=service_name,
        minutes=minutes,
        use_llm_extraction=use_llm_extraction,
        log_path=log_path,
    )


@mcp.tool()
def get_recent_deploys(
    service_name: str = "",
    limit: int = 5,
    deploys_path: str | None = None,
) -> dict:
    """
    Retrieve the most recent deployments for a service, sorted newest-first.

    Accepts an optional `deploys_path` parameter pointing directly to a JSON file
    containing deployment records. If None, falls back to `mock_data/deploys.json`.

    Args:
        service_name: Service name (e.g. "order-processing").
        limit: Maximum number of deploy records to return (default 5).
        deploys_path: Optional path to a custom deploys.json file.
    """
    return tools.get_recent_deploys(
        service_name=service_name,
        limit=limit,
        deploys_path=deploys_path,
    )


@mcp.tool()
def get_service_health(
    service_name: str = "",
    health_path: str | None = None,
) -> dict:
    """
    Return current health metrics for a service, with a plain-English flags list.

    Accepts an optional `health_path` parameter pointing directly to a JSON health
    metric file. If None, falls back to `mock_data/health.json`.

    Args:
        service_name: Service name (e.g. "order-processing").
        health_path: Optional path to a custom health.json file.
    """
    return tools.get_service_health(
        service_name=service_name,
        health_path=health_path,
    )


@mcp.tool()
def diagnose(
    service_name: str = "",
    log_path: str | None = None,
    deploys_path: str | None = None,
    health_path: str | None = None,
) -> dict:
    """
    Run a full automated diagnosis for a service and identify the likely root cause.

    Calls get_recent_errors, get_recent_deploys, and get_service_health, then
    synthesises a plain-English "likely_cause" statement.

    You can either pass `service_name` to use built-in demo data, or supply explicit
    paths (`log_path`, `deploys_path`, `health_path`) to point at real log files/folders
    and metric JSON files.

    Args:
        service_name: Service name (e.g. "order-processing").
        log_path: Optional path to a custom log file or directory of .log/.txt files.
        deploys_path: Optional path to a custom deploys.json file.
        health_path: Optional path to a custom health.json file.
    """
    return tools.diagnose(
        service_name=service_name,
        log_path=log_path,
        deploys_path=deploys_path,
        health_path=health_path,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
