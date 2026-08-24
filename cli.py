"""
cli.py — Command-line interface for DevContext.

Usage:
    devcontext diagnose --service order-processing
    devcontext diagnose --service order-processing --json
    devcontext diagnose --log-path /var/log/app.log --deploys-path deploys.json --health-path health.json
    devcontext diagnose --service order-processing --use-llm
    devcontext serve
"""

import argparse
import json
import os
import sys

from tools import diagnose, get_recent_errors


def _print_human_summary(result: dict):
    """Format and print a clean, human-readable diagnostic report."""
    service = result.get("service") or "Unknown Service"
    likely_cause = result.get("likely_cause", "No diagnosis produced.")
    errors = result.get("errors", {})
    health = result.get("health", {})
    deploys = result.get("deploys", {})

    sep = "=" * 78
    subsep = "-" * 78

    print("\n" + sep)
    print(f" DEVCONTEXT DIAGNOSTIC REPORT: {service}")
    print(sep)

    print("\n[ LIKELY CAUSE ]")
    print(f"  {likely_cause}")

    print("\n" + subsep)
    print("[ HEALTH STATUS & FLAGS ]")
    status = health.get("status", "unknown")
    flags = health.get("flags", [])
    print(f"  Status: {status.upper()}")
    if flags:
        print("  Active Flags:")
        for f in flags:
            print(f"    • {f}")
    else:
        print("  Active Flags: None (all metrics normal)")

    print("\n" + subsep)
    print("[ RECENT ERRORS & WARNS ]")
    total_flagged = errors.get("total_flagged_lines", 0)
    summary = errors.get("error_summary", {})
    print(f"  Total Flagged Lines: {total_flagged}")
    if summary:
        print("  Error Patterns:")
        for pat, info in summary.items():
            lvl = info.get("level", "ERROR")
            cnt = info.get("count", 1)
            print(f"    • [{lvl:5}] (x{cnt}) {pat}")
    else:
        print("  Error Patterns: None detected in window")

    print("\n" + subsep)
    print("[ RECENT DEPLOYMENTS ]")
    deploy_list = deploys.get("deploys", [])
    if deploy_list:
        for d in deploy_list[:3]:
            ts = d.get("timestamp", "")
            commit = d.get("commit", "unknown")
            author = d.get("author", "unknown")
            msg = d.get("message", "")
            print(f"  • {ts} | Commit: {commit} | Author: {author}")
            print(f"    Message: {msg}")
    else:
        print("  No recent deployments recorded.")

    print(sep + "\n")


def main():
    parser = argparse.ArgumentParser(
        prog="devcontext",
        description="DevContext — Runtime observability context for AI coding agents and engineers.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Command: diagnose ---
    diag_parser = subparsers.add_parser(
        "diagnose",
        help="Diagnose an incident for a service or explicit log/deploy/health paths.",
    )
    diag_parser.add_argument(
        "--service",
        type=str,
        default="",
        help="Service name to look up in built-in mock_data/ or scenario directories.",
    )
    diag_parser.add_argument(
        "--log-path",
        type=str,
        default=None,
        help="Path to a custom log file or directory containing split/rotated log files.",
    )
    diag_parser.add_argument(
        "--deploys-path",
        type=str,
        default=None,
        help="Path to a custom deploys.json file.",
    )
    diag_parser.add_argument(
        "--health-path",
        type=str,
        default=None,
        help="Path to a custom health.json file.",
    )
    diag_parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use Groq LLM extraction for log parsing (requires GROQ_API_KEY).",
    )
    diag_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of the human-readable report.",
    )

    # --- Command: serve ---
    subparsers.add_parser(
        "serve",
        help="Start the DevContext MCP server using stdio transport.",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "serve":
        from server import mcp
        print("Starting DevContext MCP Server (stdio transport)...", file=sys.stderr)
        mcp.run(transport="stdio")
        return

    if args.command == "diagnose":
        if args.use_llm:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                print(
                    "Warning: --use-llm specified but GROQ_API_KEY environment variable is not set. "
                    "Falling back to the deterministic format-adaptive parser.",
                    file=sys.stderr,
                )

        # Call diagnose
        result = diagnose(
            service_name=args.service,
            log_path=args.log_path,
            deploys_path=args.deploys_path,
            health_path=args.health_path,
        )

        # Re-run error extraction with LLM if --use-llm flag was passed
        if args.use_llm:
            llm_errors = get_recent_errors(
                service_name=args.service,
                log_path=args.log_path,
                use_llm_extraction=True,
            )
            result["errors"] = llm_errors

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_human_summary(result)


if __name__ == "__main__":
    main()
