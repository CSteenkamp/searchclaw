"""API key authentication middleware."""

import hashlib
import hmac
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.sql import func

from api.config import get_settings
from api.services.database import get_session
from api.services.cache import get_cached, set_cached, get_counter, incr_counter
from api.models.user import APIKey, User, PLAN_LIMITS

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_key(key: str) -> str:
    """HMAC-SHA256 hash an API key for storage/lookup."""
    secret = get_settings().api_key_hmac_secret
    return hmac.new(secret.encode(), key.encode(), hashlib.sha256).hexdigest()


async def get_api_key_user(
    api_key: str = Security(api_key_header),
    request: Request = None,
) -> dict:
    """Validate API key and return user info.

    Returns dict with: user_id, plan, api_key_id, rate_per_sec, monthly_credits
    """
    if not api_key:
        # Check Authorization Bearer header as fallback
        auth = request.headers.get("Authorization", "") if request else ""
        if auth.startswith("Bearer "):
            api_key = auth[7:]

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Pass X-API-Key header.")

    if not api_key.startswith("dc_"):
        raise HTTPException(status_code=401, detail="Invalid API key format.")

    key_hashed = hash_key(api_key)

    # Check Redis cache first
    cache_key = f"auth:{key_hashed}"
    cached_user = await get_cached(cache_key)
    if cached_user:
        return cached_user

    # Lookup in database
    async for session in get_session():
        stmt = (
            select(APIKey, User)
            .join(User, APIKey.user_id == User.id)
            .where(APIKey.key_hash == key_hashed, APIKey.is_active == True, User.is_active == True)
        )
        result = await session.execute(stmt)
        row = result.first()

        if not row:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")

        api_key_obj, user = row
        plan = user.plan or "free"
        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

        user_info = {
            "user_id": user.id,
            "api_key_id": api_key_obj.id,
            "plan": plan,
            "rate_per_sec": limits["rate_per_sec"],
            "monthly_credits": limits["monthly_credits"],
            "email": user.email,
        }

        # Throttle last_used_at updates to once per minute to avoid DB write amplification
        throttle_key = f"last_used:{api_key_obj.id}"
        recently_updated = await get_counter(throttle_key)
        if not recently_updated:
            api_key_obj.last_used_at = func.now()
            await session.commit()
            await incr_counter(throttle_key, ttl=60)
        else:
            await session.close()

        # Cache for 5 minutes
        await set_cached(cache_key, user_info, ttl=300)

        return user_info

    raise HTTPException(status_code=401, detail="Authentication failed.")
