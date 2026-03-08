"""Tests for organisation management endpoints — /v1/orgs."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import app
from api.middleware.auth import get_api_key_user


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def org_owner():
    """Mock user who will own an org."""
    user_info = {
        "user_id": 10,
        "api_key_id": 10,
        "plan": "pro",
        "rate_per_sec": 20,
        "monthly_credits": 100000,
        "email": "owner@acme.com",
    }

    async def override():
        return user_info

    app.dependency_overrides[get_api_key_user] = override
    yield user_info
    app.dependency_overrides.pop(get_api_key_user, None)


# ── Create Org ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_org_requires_auth(client):
    """POST /v1/orgs without auth returns 401."""
    resp = await client.post("/v1/orgs", json={"name": "Acme", "slug": "acme"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_org_success(client, org_owner, mock_redis):
    """POST /v1/orgs creates an org and assigns caller as owner."""
    with patch("api.routers.orgs.get_session") as mock_session:
        session = AsyncMock()

        # No existing org with slug
        result_none = MagicMock()
        result_none.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_none)

        fake_org = MagicMock()
        fake_org.id = 1
        fake_org.name = "Acme"
        fake_org.slug = "acme"
        fake_org.plan = "free"

        original_add = session.add

        def capture_add(obj):
            if hasattr(obj, "slug"):
                obj.id = 1
                obj.name = "Acme"
                obj.slug = "acme"
                obj.plan = "free"

        session.add = capture_add
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.post("/v1/orgs", json={"name": "Acme", "slug": "acme"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "acme"


@pytest.mark.asyncio
async def test_create_org_duplicate_slug(client, org_owner, mock_redis):
    """POST /v1/orgs with existing slug returns 409."""
    with patch("api.routers.orgs.get_session") as mock_session:
        session = AsyncMock()
        existing_org = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_org
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.post("/v1/orgs", json={"name": "Acme", "slug": "acme"})
        assert resp.status_code == 409


# ── Get Org ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_org_not_found(client, org_owner, mock_redis):
    """GET /v1/orgs/{slug} with unknown slug returns 404."""
    with patch("api.routers.orgs._get_org_and_check_role", side_effect=__import__("fastapi").HTTPException(404, "Organisation not found.")):
        resp = await client.get("/v1/orgs/nonexistent")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_org_requires_auth(client):
    """GET /v1/orgs/{slug} without auth returns 401."""
    resp = await client.get("/v1/orgs/acme")
    assert resp.status_code == 401


# ── Invite Member ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_member_requires_auth(client):
    """POST /v1/orgs/{slug}/members without auth returns 401."""
    resp = await client.post("/v1/orgs/acme/members", json={"email": "user@example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invite_member_invalid_role(client, org_owner, mock_redis):
    """POST /v1/orgs/{slug}/members with invalid role returns 422."""
    with patch("api.routers.orgs._get_org_and_check_role") as mock_check:
        mock_check.return_value = (MagicMock(id=1), MagicMock(role="admin"))
        resp = await client.post("/v1/orgs/acme/members", json={"email": "user@example.com", "role": "owner"})
        assert resp.status_code == 422


# ── Remove Member ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_member_requires_auth(client):
    """DELETE /v1/orgs/{slug}/members/{id} without auth returns 401."""
    resp = await client.delete("/v1/orgs/acme/members/99")
    assert resp.status_code == 401


# ── Org Keys ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_org_key_invalid_env(client, org_owner, mock_redis):
    """POST /v1/orgs/{slug}/keys with bad environment returns 422."""
    with patch("api.routers.orgs._get_org_and_check_role") as mock_check:
        mock_check.return_value = (MagicMock(id=1), MagicMock(role="admin"))
        resp = await client.post("/v1/orgs/acme/keys", json={"name": "Key", "environment": "invalid"})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_org_keys_requires_auth(client):
    """GET /v1/orgs/{slug}/keys without auth returns 401."""
    resp = await client.get("/v1/orgs/acme/keys")
    assert resp.status_code == 401


# ── Org Usage ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_usage_requires_auth(client):
    """GET /v1/orgs/{slug}/usage without auth returns 401."""
    resp = await client.get("/v1/orgs/acme/usage")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_org_usage_csv_format(client, org_owner, mock_redis):
    """GET /v1/orgs/{slug}/usage?format=csv returns CSV content type."""
    with patch("api.routers.orgs._get_org_and_check_role") as mock_check:
        mock_org = MagicMock(id=1, slug="acme", plan="pro", monthly_credits=100000)
        mock_check.return_value = (mock_org, MagicMock(role="owner"))

        with patch("api.routers.orgs.get_session") as mock_session:
            session = AsyncMock()
            result = MagicMock()
            result.all.return_value = []
            session.execute = AsyncMock(return_value=result)

            async def gen():
                yield session

            mock_session.return_value = gen()

            resp = await client.get("/v1/orgs/acme/usage?format=csv")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
