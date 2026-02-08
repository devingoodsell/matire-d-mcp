"""MCP tools for viewing API usage costs."""

import logging

from fastmcp import FastMCP

from src.server import get_db

logger = logging.getLogger(__name__)


def register_cost_tools(mcp: FastMCP) -> None:
    """Register API cost tracking tools on the MCP server."""

    @mcp.tool
    async def api_costs(days: int = 30) -> str:
        """Show API usage costs broken down by provider.

        Args:
            days: Number of days to look back (default 30).

        Returns:
            Formatted table of API costs per provider.
        """
        db = get_db()
        stats = await db.get_api_call_stats(days=days)

        if not stats:
            return f"No API calls recorded in the last {days} days."

        lines = [f"API usage (last {days} days):\n"]
        total_cost = 0.0

        for s in stats:
            provider = s["provider"]
            total_calls = s["total_calls"]
            cached_calls = s["cached_calls"]
            cost_cents = s["total_cost_cents"]
            total_cost += cost_cents

            cost_str = f"${cost_cents / 100:.2f}" if cost_cents > 0 else "free tier"
            cache_rate = (
                f"{cached_calls / total_calls * 100:.0f}%"
                if total_calls > 0
                else "0%"
            )

            lines.append(
                f"  {provider}: {cost_str} ({total_calls} calls, "
                f"{cache_rate} cache hit rate)"
            )

        lines.append(f"\nTotal: ${total_cost / 100:.2f}")
        return "\n".join(lines)
