"""Stripe billing integration using the Meters API for usage-based billing."""

import stripe
from datetime import datetime, timezone
from typing import Optional

from api.config import get_settings
from api.models.user import PLAN_LIMITS

# Plan name -> Stripe price config key mapping
PLAN_PRICE_MAP = {
    "starter": "stripe_price_starter",
    "pro": "stripe_price_pro",
    "scale": "stripe_price_scale",
}


def _configure_stripe():
    """Set Stripe API key from settings."""
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key


def _get_price_id(plan: str) -> str:
    """Get the Stripe Price ID for a plan."""
    settings = get_settings()
    config_key = PLAN_PRICE_MAP.get(plan)
    if not config_key:
        raise ValueError(f"No Stripe price configured for plan: {plan}")
    price_id = getattr(settings, config_key, "")
    if not price_id:
        raise ValueError(f"Stripe price ID not set for plan: {plan}")
    return price_id


def create_stripe_customer(email: str, name: str = "") -> str:
    """Create a Stripe customer and return the customer ID."""
    _configure_stripe()
    customer = stripe.Customer.create(
        email=email,
        name=name or email,
        metadata={"source": "searchclaw"},
    )
    return customer.id


def create_checkout_session(
    stripe_customer_id: str,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session for initial subscription signup.

    Returns the checkout session URL.
    """
    _configure_stripe()
    price_id = _get_price_id(plan)
    settings = get_settings()

    line_items = [{"price": price_id, "quantity": 1}]

    # Add metered overage price if configured
    if settings.stripe_price_metered:
        line_items.append({"price": settings.stripe_price_metered})

    session = stripe.checkout.Session.create(
        customer=stripe_customer_id,
        mode="subscription",
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"plan": plan},
    )
    return session.url


def create_customer_portal_url(stripe_customer_id: str, return_url: str) -> str:
    """Generate a Stripe Customer Portal URL for self-service billing management."""
    _configure_stripe()
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session.url


def create_subscription(stripe_customer_id: str, plan: str) -> stripe.Subscription:
    """Create a subscription for a paid plan."""
    _configure_stripe()
    price_id = _get_price_id(plan)
    settings = get_settings()

    items = [{"price": price_id}]
    if settings.stripe_price_metered:
        items.append({"price": settings.stripe_price_metered})

    subscription = stripe.Subscription.create(
        customer=stripe_customer_id,
        items=items,
        metadata={"plan": plan},
    )
    return subscription


def update_subscription_plan(
    subscription_id: str, new_plan: str
) -> stripe.Subscription:
    """Upgrade or downgrade a subscription to a new plan."""
    _configure_stripe()
    new_price_id = _get_price_id(new_plan)

    subscription = stripe.Subscription.retrieve(subscription_id)

    # Find the fixed-price item (not the metered one)
    fixed_item = None
    for item in subscription["items"]["data"]:
        if item["price"]["type"] == "recurring" and item["price"]["recurring"].get("usage_type") != "metered":
            fixed_item = item
            break

    if not fixed_item:
        raise ValueError("Could not find fixed-price subscription item")

    updated = stripe.Subscription.modify(
        subscription_id,
        items=[{"id": fixed_item["id"], "price": new_price_id}],
        proration_behavior="create_prorations",
        metadata={"plan": new_plan},
    )
    return updated


def send_meter_event(stripe_customer_id: str, quantity: int, timestamp: Optional[int] = None):
    """Send a meter event to Stripe's Billing Meters API.

    This replaces the older SubscriptionItem.create_usage_record() approach.
    Stripe aggregates these events automatically based on the meter's config.
    """
    _configure_stripe()
    settings = get_settings()
    ts = timestamp or int(datetime.now(timezone.utc).timestamp())

    stripe.billing.MeterEvent.create(
        event_name=settings.stripe_meter_event_name,
        payload={
            "value": str(quantity),
            "stripe_customer_id": stripe_customer_id,
        },
        timestamp=ts,
    )
