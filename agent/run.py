#!/usr/bin/env python3
"""
Entry point for the Contortion Space Monthly Performance Review Agent.

Usage:
    python -m agent.run                          # defaults to current month
    python -m agent.run --month "June 2026"
    python -m agent.run --month "July 2026" --quiet

Required environment variables:
    ANTHROPIC_API_KEY   Claude API key
    NOTION_API_KEY      Notion integration token
    WEBFLOW_API_KEY     Webflow API token (v2)
    TAVILY_API_KEY      Tavily search API key  (OR)
    SERPER_API_KEY      Serper.dev search API key
"""

import argparse
import os
import sys
from datetime import datetime

from .luzia_agent import run


def _current_month_label() -> str:
    return datetime.now().strftime("%B %Y")


def _check_env() -> list[str]:
    missing = []
    for var in ("ANTHROPIC_API_KEY", "NOTION_API_KEY", "WEBFLOW_API_KEY"):
        if not os.environ.get(var):
            missing.append(var)
    if not os.environ.get("TAVILY_API_KEY") and not os.environ.get("SERPER_API_KEY"):
        missing.append("TAVILY_API_KEY or SERPER_API_KEY")
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a monthly contortion performance review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--month",
        default=_current_month_label(),
        help="Month to review, e.g. 'June 2026' (default: current month)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose tool-call logging",
    )
    args = parser.parse_args()

    missing = _check_env()
    if missing:
        print("❌ Missing required environment variables:")
        for m in missing:
            print(f"   • {m}")
        sys.exit(1)

    run(month_label=args.month, verbose=not args.quiet)


if __name__ == "__main__":
    main()
