"""Billing endpoints — Stripe Checkout, Portal, Webhooks, Plans."""

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from api.config import get_settings
from api.middleware.auth import get_api_key_user
from api.services import billing as billing_service
from api.services.database import get_session
from api.models.user import User, PLAN_LIMITS
from sqlalchemy import select

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans")
async def list_plans():
    """List available plans with pricing details."""
    plans = []
    for slug, details in PLAN_LIMITS.items():
        plans.append({
            "name": details["name"],
            "slug": slug,
            "price_cents": details["price_cents"],
            "credits": details["monthly_credits"],
            "rate_per_sec": details["rate_per_sec"],
        })
    return {"plans": plans, "overage_per_1k": 150}


@router.post("/checkout")
async def create_checkout(
    request: Request,
    user_info: dict = Depends(get_api_key_user),
):
    """Create a Stripe Checkout session for subscribing to a paid plan."""
    body = await request.json()
    plan = body.get("plan", "").lower()
    success_url = body.get("success_url", "https://searchclaw.dev/billing?success=1")
    cancel_url = body.get("cancel_url", "https://searchclaw.dev/billing?cancelled=1")

    if plan not in ("starter", "pro", "scale"):
        raise HTTPException(status_code=400, detail="Invalid plan. Choose starter, pro, or scale.")

    # Get user's Stripe customer ID
    async for session in get_session():
        result = await session.execute(select(User).where(User.id == user_info["user_id"]))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        # Create Stripe customer if needed
        if not user.stripe_customer_id:
            customer_id = billing_service.create_stripe_customer(user.email, user.name)
            user.stripe_customer_id = customer_id
            await session.commit()
        else:
            customer_id = user.stripe_customer_id

    try:
        checkout_url = billing_service.create_checkout_session(
            stripe_customer_id=customer_id,
            plan=plan,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"checkout_url": checkout_url}


@router.get("/portal")
async def customer_portal(
    user_info: dict = Depends(get_api_key_user),
):
    """Redirect to Stripe Customer Portal for self-service billing management."""
    async for session in get_session():
        result = await session.execute(select(User).where(User.id == user_info["user_id"]))
        user = result.scalar_one_or_none()
        if not user or not user.stripe_customer_id:
            raise HTTPException(status_code=400, detail="No billing account found. Subscribe to a plan first.")

    return_url = "https://searchclaw.dev/billing"
    portal_url = billing_service.create_customer_portal_url(user.stripe_customer_id, return_url)
    return RedirectResponse(url=portal_url)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature.")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)

    return JSONResponse(content={"status": "ok"})


async def _handle_checkout_completed(session_data: dict):
    """Handle checkout.session.completed — activate the user's plan."""
    customer_id = session_data.get("customer")
    plan = session_data.get("metadata", {}).get("plan", "starter")

    async for session in get_session():
        result = await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.plan = plan
            await session.commit()


async def _handle_invoice_paid(invoice: dict):
    """Handle invoice.paid — confirm subscription is active."""
    customer_id = invoice.get("customer")
    async for session in get_session():
        result = await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.is_active = True
            await session.commit()


async def _handle_payment_failed(invoice: dict):
    """Handle invoice.payment_failed — mark user for follow-up."""
    # For now, just log. Could send email or restrict access after grace period.
    pass


async def _handle_subscription_deleted(subscription: dict):
    """Handle customer.subscription.deleted — revert user to free plan."""
    customer_id = subscription.get("customer")

    async for session in get_session():
        result = await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.plan = "free"
            await session.commit()


async def _handle_subscription_updated(subscription: dict):
    """Handle customer.subscription.updated — sync plan changes."""
    customer_id = subscription.get("customer")
    plan = subscription.get("metadata", {}).get("plan")
    status = subscription.get("status")

    async for session in get_session():
        result = await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user:
            if plan:
                user.plan = plan
            if status == "canceled":
                user.plan = "free"
            await session.commit()
