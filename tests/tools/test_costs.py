"""Tests for src.tools.costs — API cost tracking MCP tool."""

from unittest.mock import patch

import pytest
from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.costs import register_cost_tools


@pytest.fixture
async def db():
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def cost_mcp(db):
    test_mcp = FastMCP("test")
    db_patch = patch("src.tools.costs.get_db", return_value=db)
    db_patch.start()
    register_cost_tools(test_mcp)
    yield test_mcp, db
    db_patch.stop()


class TestApiCostsTool:
    async def test_no_calls_recorded(self, cost_mcp):
        mcp, db = cost_mcp
        async with Client(mcp) as client:
            result = await client.call_tool("api_costs", {"days": 30})
        text = str(result)
        assert "No API calls" in text

    async def test_shows_costs_by_provider(self, cost_mcp):
        mcp, db = cost_mcp
        await db.log_api_call("google_places", "searchText", 3.2, 200, False)
        await db.log_api_call("google_places", "searchText", 3.2, 200, True)
        await db.log_api_call("resy", "availability", 0.0, 200, False)
        async with Client(mcp) as client:
            result = await client.call_tool("api_costs", {"days": 30})
        text = str(result)
        assert "google_places" in text
        assert "$0.06" in text  # 6.4 cents
        assert "resy" in text
        assert "free tier" in text

    async def test_cache_hit_rate_displayed(self, cost_mcp):
        mcp, db = cost_mcp
        await db.log_api_call("google_places", "searchText", 3.2, 200, False)
        await db.log_api_call("google_places", "searchText", 3.2, 200, True)
        async with Client(mcp) as client:
            result = await client.call_tool("api_costs", {"days": 30})
        text = str(result)
        assert "50%" in text  # 1 of 2 cached

    async def test_total_cost_shown(self, cost_mcp):
        mcp, db = cost_mcp
        await db.log_api_call("google_places", "searchText", 100.0, 200, False)
        async with Client(mcp) as client:
            result = await client.call_tool("api_costs", {"days": 30})
        text = str(result)
        assert "Total: $1.00" in text

    async def test_custom_days_parameter(self, cost_mcp):
        mcp, db = cost_mcp
        await db.log_api_call("google_places", "searchText", 3.2, 200, False)
        async with Client(mcp) as client:
            result = await client.call_tool("api_costs", {"days": 7})
        text = str(result)
        assert "last 7 days" in text
