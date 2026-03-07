"""Tests for authentication middleware and registration flow."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_missing_api_key(client):
    resp = await client.get("/v1/search", params={"q": "test"})
    assert resp.status_code == 401
    assert "Missing API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_api_key_format(client):
    resp = await client.get(
        "/v1/search",
        params={"q": "test"},
        headers={"X-API-Key": "bad_key_format"},
    )
    assert resp.status_code == 401
    assert "Invalid API key format" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_bearer_token_fallback(client):
    """Authorization: Bearer should work as fallback."""
    resp = await client.get(
        "/v1/search",
        params={"q": "test"},
        headers={"Authorization": "Bearer bad_format"},
    )
    assert resp.status_code == 401
    assert "Invalid API key format" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_valid_dc_prefix_but_not_found(client, mock_redis):
    """Valid prefix but key not in DB should return 401."""
    with patch("api.middleware.auth.get_session") as mock_session:
        # Mock DB returning no results
        session = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get(
            "/v1/search",
            params={"q": "test"},
            headers={"X-API-Key": "dc_live_deadbeef1234567890abcdef"},
        )
        assert resp.status_code == 401


def test_hash_key_is_hmac():
    """Verify hash_key uses HMAC-SHA256, not bare SHA256."""
    import hashlib
    from api.middleware.auth import hash_key

    key = "dc_live_test123"
    hashed = hash_key(key)

    # Should NOT equal bare SHA256
    bare_sha = hashlib.sha256(key.encode()).hexdigest()
    assert hashed != bare_sha

    # Should be deterministic
    assert hash_key(key) == hash_key(key)

    # Different keys should produce different hashes
    assert hash_key("dc_live_aaa") != hash_key("dc_live_bbb")
