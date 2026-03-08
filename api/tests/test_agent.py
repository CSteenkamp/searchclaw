"""Tests for agent endpoint — POST /v1/agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.models.agent import AgentResponse, AgentStep, AgentSource
from api.services.query_generator import generate_search_queries, _extract_keywords


# ----- Query generator tests -----

class TestQueryGenerator:
    def test_basic_prompt(self):
        """Test query generation from a simple prompt."""
        queries = generate_search_queries("Find the founding team of Stripe")
        assert len(queries) >= 1
        assert len(queries) <= 3
        # Should contain relevant keywords
        combined = " ".join(queries).lower()
        assert "stripe" in combined
        assert "founding" in combined or "team" in combined

    def test_empty_prompt(self):
        """Test query generation with empty-ish prompt."""
        queries = generate_search_queries("the")
        assert len(queries) >= 1

    def test_max_queries_limit(self):
        """Test that max_queries is respected."""
        queries = generate_search_queries("Find all Python web frameworks with async support", max_queries=1)
        assert len(queries) == 1

    def test_keyword_extraction(self):
        """Test internal keyword extraction."""
        keywords = _extract_keywords("Find the founding team of Stripe with their roles")
        assert "stripe" in keywords
        assert "roles" in keywords
        # Stop words should be filtered
        assert "the" not in keywords
        assert "of" not in keywords


# ----- URL filtering/scoring tests -----

class TestURLScoring:
    def test_score_url(self):
        from api.services.agent_service import _score_url
        score = _score_url("Stripe Founders", "Patrick and John Collison founded Stripe", ["stripe", "founders"])
        assert score > 0

    def test_score_url_no_match(self):
        from api.services.agent_service import _score_url
        score = _score_url("Unrelated Page", "Nothing relevant here", ["stripe", "founders"])
        assert score == 0.0


# ----- Structured merge tests -----

class TestStructuredMerge:
    def test_merge_dicts(self):
        from api.services.agent_service import _merge_structured
        result = _merge_structured([
            {"name": "Patrick", "role": "CEO"},
            {"name": "John", "company": "Stripe"},
        ])
        assert result["name"] == "Patrick"  # First wins for scalar
        assert result["role"] == "CEO"
        assert result["company"] == "Stripe"

    def test_merge_arrays_dedup(self):
        from api.services.agent_service import _merge_structured
        result = _merge_structured([
            {"items": [{"name": "A"}, {"name": "B"}]},
            {"items": [{"name": "B"}, {"name": "C"}]},
        ])
        assert len(result["items"]) == 3

    def test_merge_empty(self):
        from api.services.agent_service import _merge_structured
        result = _merge_structured([])
        assert result == {}


# ----- Agent endpoint tests -----

@pytest.fixture
def mock_agent_run():
    """Mock the run_agent service to return a fake result."""
    result = AgentResponse(
        success=True,
        status="completed",
        data={"founders": [{"name": "Patrick Collison", "role": "CEO"}]},
        sources=[AgentSource(url="https://stripe.com/about", title="About Stripe")],
        credits_used=3,
        steps=[
            AgentStep(phase="search", queries=["Stripe founding team"], results=10),
            AgentStep(phase="filter", urls_selected=2),
            AgentStep(phase="extract", pages_processed=2, pages_succeeded=2),
            AgentStep(phase="merge", output_type="structured"),
        ],
    )
    with patch("api.routers.agent.run_agent", new_callable=AsyncMock, return_value=result) as mock:
        yield mock, result


@pytest.mark.asyncio
async def test_agent_sync_mode(client, mock_db_user, mock_redis, mock_agent_run):
    """Test agent in sync mode (max_credits <= 10)."""
    mock, expected = mock_agent_run
    resp = await client.post("/v1/agent", json={
        "prompt": "Find the founding team of Stripe",
        "schema": {"founders": []},
        "max_credits": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "completed"
    assert data["credits_used"] == 3
    assert len(data["sources"]) == 1
    assert len(data["steps"]) == 4
    mock.assert_called_once()


@pytest.mark.asyncio
async def test_agent_async_mode_high_credits(client, mock_db_user, mock_redis, mock_agent_run):
    """Test agent in async mode when max_credits > 10."""
    mock, _ = mock_agent_run
    resp = await client.post("/v1/agent", json={
        "prompt": "Find all Python web frameworks",
        "max_credits": 20,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["job_id"] is not None
    assert data["job_id"].startswith("agent_")


@pytest.mark.asyncio
async def test_agent_async_mode_webhook(client, mock_db_user, mock_redis, mock_agent_run):
    """Test agent in async mode when webhook is provided."""
    mock, _ = mock_agent_run
    resp = await client.post("/v1/agent", json={
        "prompt": "Find Stripe founders",
        "max_credits": 5,
        "webhook_url": "https://myapp.com/webhook",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["job_id"] is not None


@pytest.mark.asyncio
async def test_agent_credit_cap_enforcement(client, mock_db_user, mock_redis, mock_agent_run):
    """Test that unused credits are released."""
    mock, result = mock_agent_run
    # max_credits=10, agent uses 3 → should release 7
    resp = await client.post("/v1/agent", json={
        "prompt": "Find Stripe founders",
        "max_credits": 10,
    })
    assert resp.status_code == 200
    assert resp.json()["credits_used"] == 3


@pytest.mark.asyncio
async def test_agent_no_auth(client, mock_redis):
    """Test that agent requires authentication."""
    resp = await client.post("/v1/agent", json={
        "prompt": "Find something",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_agent_missing_prompt(client, mock_db_user, mock_redis):
    """Test that prompt is required."""
    resp = await client.post("/v1/agent", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_agent_max_credits_cap(client, mock_db_user, mock_redis):
    """Test that max_credits > 50 is rejected."""
    resp = await client.post("/v1/agent", json={
        "prompt": "Find something",
        "max_credits": 51,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_agent_without_schema(client, mock_db_user, mock_redis):
    """Test agent works without schema (returns markdown)."""
    result = AgentResponse(
        success=True,
        status="completed",
        data="## Source: https://example.com\n\nSome content",
        sources=[AgentSource(url="https://example.com", title="Example")],
        credits_used=2,
        steps=[
            AgentStep(phase="search", queries=["example"], results=5),
            AgentStep(phase="filter", urls_selected=1),
            AgentStep(phase="extract", pages_processed=1, pages_succeeded=1),
            AgentStep(phase="merge", output_type="markdown"),
        ],
    )
    with patch("api.routers.agent.run_agent", new_callable=AsyncMock, return_value=result):
        resp = await client.post("/v1/agent", json={
            "prompt": "Find example content",
            "max_credits": 5,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["data"], str)
    assert "Source:" in data["data"]


@pytest.mark.asyncio
async def test_agent_with_seed_urls(client, mock_db_user, mock_redis, mock_agent_run):
    """Test agent with pre-provided seed URLs."""
    mock, _ = mock_agent_run
    resp = await client.post("/v1/agent", json={
        "prompt": "Extract product info",
        "urls": ["https://example.com/product1", "https://example.com/product2"],
        "max_credits": 5,
    })
    assert resp.status_code == 200
    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs.kwargs.get("urls") is not None


@pytest.mark.asyncio
async def test_agent_steps_trace(client, mock_db_user, mock_redis, mock_agent_run):
    """Test that response includes step-by-step trace."""
    resp = await client.post("/v1/agent", json={
        "prompt": "Find Stripe founders",
        "max_credits": 5,
    })
    data = resp.json()
    steps = data["steps"]
    phases = [s["phase"] for s in steps]
    assert phases == ["search", "filter", "extract", "merge"]
