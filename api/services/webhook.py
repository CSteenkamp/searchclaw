"""Webhook delivery service for async job completion notifications."""

import asyncio
import hashlib
import hmac
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 5, 25]  # seconds — exponential backoff
REQUEST_TIMEOUT = 10.0  # seconds per attempt


async def deliver_webhook(
    job_id: str,
    payload: dict,
    webhook_url: str,
    webhook_secret: str | None = None,
    event: str = "job.completed",
) -> dict:
    """POST job results to the client's webhook URL with HMAC signing and retries.

    Returns a dict with delivery metadata: delivered, attempts, last_error.
    """
    body = json.dumps(payload, separators=(",", ":"), default=str)
    body_bytes = body.encode()

    headers = {
        "Content-Type": "application/json",
        "X-SearchClaw-Event": event,
        "X-SearchClaw-Job-Id": job_id,
        "User-Agent": "SearchClaw-Webhook/1.0",
    }

    if webhook_secret:
        signature = hmac.new(
            webhook_secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
        headers["X-SearchClaw-Signature"] = f"sha256={signature}"

    last_error = None
    attempts = 0

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for i, delay in enumerate(RETRY_DELAYS):
            attempts += 1
            try:
                resp = await client.post(
                    webhook_url, content=body_bytes, headers=headers
                )
                if resp.status_code < 400:
                    logger.info(
                        "Webhook delivered for job %s (attempt %d, status %d)",
                        job_id, attempts, resp.status_code,
                    )
                    return {
                        "webhook_delivered": True,
                        "webhook_attempts": attempts,
                        "webhook_last_error": None,
                    }
                last_error = f"HTTP {resp.status_code}"
                logger.warning(
                    "Webhook delivery failed for job %s (attempt %d): %s",
                    job_id, attempts, last_error,
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Webhook delivery error for job %s (attempt %d): %s",
                    job_id, attempts, last_error,
                )

            # Don't sleep after the last attempt
            if i < len(RETRY_DELAYS) - 1:
                await asyncio.sleep(delay)

    logger.error(
        "Webhook delivery exhausted for job %s after %d attempts: %s",
        job_id, attempts, last_error,
    )
    return {
        "webhook_delivered": False,
        "webhook_attempts": attempts,
        "webhook_last_error": last_error,
    }
