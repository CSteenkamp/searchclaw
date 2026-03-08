"""POST /v1/agent — autonomous data gathering from natural language prompts."""

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.agent import AgentRequest, AgentResponse
from api.services.agent_service import run_agent
from api.services.cache import get_redis_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])


@router.post(
    "/agent",
    response_model=AgentResponse,
    summary="Autonomous data gathering",
    description="Accept a natural language prompt and optionally a schema, then search, "
    "navigate, and extract data autonomously. Sync if max_credits <= 10 and no webhook, "
    "otherwise async with webhook delivery.",
    responses={
        200: {"description": "Agent result (sync) or job accepted (async)"},
        402: {"description": "Insufficient credits"},
    },
)
async def agent_endpoint(
    req: AgentRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> AgentResponse:
    rl_headers = await check_rate_limit(user_info)

    # Determine sync vs async mode
    is_async = req.max_credits > 10 or req.webhook_url is not None

    if is_async:
        return await _handle_async(req, response, user_info, rl_headers)
    else:
        return await _handle_sync(req, response, user_info, rl_headers)


async def _handle_sync(
    req: AgentRequest, response: Response, user_info: dict, rl_headers: dict,
) -> AgentResponse:
    """Run agent synchronously and return result directly."""
    credit_headers = await reserve_credits(user_info, credits=req.max_credits)

    start = time.monotonic()
    completed = False
    actual_credits = 0

    try:
        result = await run_agent(
            prompt=req.prompt,
            schema=req.schema_,
            urls=[str(u) for u in req.urls] if req.urls else None,
            max_credits=req.max_credits,
            max_sources=req.max_sources,
        )
        actual_credits = result.credits_used

        # Release unused credits
        unused = req.max_credits - actual_credits
        if unused > 0:
            await release_credits(user_info, unused)

        completed = True
        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v
        return result

    except HTTPException:
        raise
    except Exception:
        await release_credits(user_info, req.max_credits)
        raise
    finally:
        if completed:
            elapsed = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                record_usage_to_db(
                    user_info["api_key_id"], "/v1/agent",
                    actual_credits, False, elapsed,
                )
            )


async def _handle_async(
    req: AgentRequest, response: Response, user_info: dict, rl_headers: dict,
) -> AgentResponse:
    """Create an async agent job, run in background, deliver via webhook."""
    credit_headers = await reserve_credits(user_info, credits=req.max_credits)

    job_id = f"agent_{uuid.uuid4().hex[:12]}"

    # Store initial job status
    redis = get_redis_client()
    if redis:
        await redis.set(
            f"job:{job_id}:status",
            json.dumps({"status": "processing", "credits_used": 0}),
            ex=3600,
        )

    # Launch background task
    asyncio.create_task(
        _run_async_agent(job_id, req, user_info)
    )

    for k, v in {**rl_headers, **credit_headers}.items():
        response.headers[k] = v

    return AgentResponse(
        success=True,
        status="processing",
        job_id=job_id,
    )


async def _run_async_agent(job_id: str, req: AgentRequest, user_info: dict):
    """Background task: run agent and deliver result via webhook."""
    try:
        result = await run_agent(
            prompt=req.prompt,
            schema=req.schema_,
            urls=[str(u) for u in req.urls] if req.urls else None,
            max_credits=req.max_credits,
            max_sources=req.max_sources,
        )

        # Release unused credits
        unused = req.max_credits - result.credits_used
        if unused > 0:
            await release_credits(user_info, unused)

        # Store result in Redis
        redis = get_redis_client()
        if redis:
            await redis.set(
                f"job:{job_id}:status",
                json.dumps({"status": "completed", "credits_used": result.credits_used}),
                ex=3600,
            )
            await redis.set(
                f"job:{job_id}:result",
                result.model_dump_json(),
                ex=3600,
            )

        # Deliver via webhook
        if req.webhook_url:
            await _deliver_webhook(str(req.webhook_url), result, req.webhook_secret)

        # Record usage
        await record_usage_to_db(
            user_info["api_key_id"], "/v1/agent", result.credits_used, False, 0,
        )

    except Exception as e:
        logger.error("Async agent job %s failed: %s", job_id, e)
        redis = get_redis_client()
        if redis:
            await redis.set(
                f"job:{job_id}:status",
                json.dumps({"status": "failed", "error": str(e)}),
                ex=3600,
            )
        await release_credits(user_info, req.max_credits)


async def _deliver_webhook(url: str, result: AgentResponse, secret: str | None):
    """POST agent result to the webhook URL."""
    import hashlib
    import hmac
    import httpx

    payload = result.model_dump_json()
    headers = {"Content-Type": "application/json"}

    if secret:
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = sig

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, content=payload, headers=headers)
    except Exception as e:
        logger.warning("Webhook delivery failed for %s: %s", url, e)
