"""Rate limiting and credit management using Redis."""

import time
from datetime import datetime, timezone
from fastapi import HTTPException

from api.services.cache import incr_counter, decr_counter


async def check_rate_limit(user_info: dict) -> dict:
    """Check per-second rate limit for authenticated user.

    For org keys, rate limiting is shared at the org level.
    Returns dict with rate limit headers.
    """
    # Org keys share rate limits at the org level
    org_id = user_info.get("org_id")
    rl_scope = f"org:{org_id}" if org_id else str(user_info["api_key_id"])
    rate_per_sec = user_info["rate_per_sec"]

    # Sliding window: count requests in current second
    window_key = f"rl:{rl_scope}:{int(time.time())}"
    count = await incr_counter(window_key, ttl=2)

    remaining = max(0, rate_per_sec - count)
    reset_at = int(time.time()) + 1

    headers = {
        "X-RateLimit-Limit": str(rate_per_sec),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_at),
    }

    if count > rate_per_sec:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Upgrade your plan for higher limits.",
            headers={"Retry-After": "1", **headers},
        )

    return headers


async def reserve_credits(user_info: dict, credits: int = 1) -> dict:
    """Atomically reserve credits via INCR. Raises 429 if over limit.

    For org keys, credits are shared across the org pool.
    """
    now = datetime.now(timezone.utc)
    org_id = user_info.get("org_id")
    credit_scope = f"org:{org_id}" if org_id else str(user_info["api_key_id"])
    monthly_credits = user_info["monthly_credits"]
    month_key = f"usage:{credit_scope}:{now.year}:{now.month}"

    used = await incr_counter(month_key, amount=credits, ttl=35 * 86400)
    remaining = max(0, monthly_credits - used)

    headers = {
        "X-Credits-Used": str(used),
        "X-Credits-Remaining": str(remaining),
    }

    if used > monthly_credits:
        # Over limit — roll back the reservation
        await decr_counter(month_key, credits)
        headers["X-Credits-Used"] = str(used - credits)
        headers["X-Credits-Remaining"] = str(max(0, monthly_credits - (used - credits)))
        raise HTTPException(
            status_code=429,
            detail="Monthly credit limit reached. Upgrade your plan or wait for reset.",
            headers=headers,
        )

    return headers


async def release_credits(user_info: dict, credits: int = 1):
    """Release previously reserved credits (e.g., on search failure)."""
    now = datetime.now(timezone.utc)
    org_id = user_info.get("org_id")
    credit_scope = f"org:{org_id}" if org_id else str(user_info["api_key_id"])
    month_key = f"usage:{credit_scope}:{now.year}:{now.month}"
    await decr_counter(month_key, credits)


async def record_usage_to_db(
    api_key_id: int, endpoint: str, credits: int, cached: bool, response_time_ms: int,
    org_id: int | None = None, query_content: str | None = None,
    data_retention: bool = True,
):
    """Persist a usage record to PostgreSQL for audit trail (fire-and-forget).

    When data_retention=False, query_content is omitted from the record.
    """
    try:
        from api.services.database import get_session
        from api.models.user import UsageRecord

        async for session in get_session():
            record = UsageRecord(
                api_key_id=api_key_id,
                org_id=org_id,
                endpoint=endpoint,
                credits_used=credits,
                cached=cached,
                response_time_ms=response_time_ms,
            )
            session.add(record)
            await session.commit()
    except Exception:
        pass
