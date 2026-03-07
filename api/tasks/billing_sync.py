"""Celery task to sync overage usage to Stripe Billing Meters hourly."""

from datetime import datetime, timedelta, timezone
from celery import Celery
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models.user import User, UsageRecord, APIKey, PLAN_LIMITS
from api.services.billing import send_meter_event, _configure_stripe

settings = get_settings()

# Celery app using Redis as broker
celery_app = Celery(
    "dataclaw",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.beat_schedule = {
    "sync-usage-to-stripe": {
        "task": "api.tasks.billing_sync.sync_usage_to_stripe",
        "schedule": 3600.0,  # every hour
    },
}


def _get_sync_engine():
    """Get a synchronous SQLAlchemy engine for Celery tasks."""
    db_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(db_url)


@celery_app.task(name="api.tasks.billing_sync.sync_usage_to_stripe")
def sync_usage_to_stripe():
    """Push overage usage to Stripe Billing Meters for all paid users.

    Runs hourly via Celery Beat. For each user on a paid plan with a Stripe
    customer ID, calculates credits used in the last hour beyond their plan
    allowance and sends a meter event for the overage amount.
    """
    _configure_stripe()
    engine = _get_sync_engine()
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    # Start of current billing period (first of month)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        # Get all paid users with Stripe customer IDs
        users = session.execute(
            select(User).where(
                User.stripe_customer_id != "",
                User.plan.in_(["starter", "pro", "scale"]),
                User.is_active == True,
            )
        ).scalars().all()

        for user in users:
            plan_credits = PLAN_LIMITS.get(user.plan, {}).get("monthly_credits", 0)

            # Total credits used this billing period
            total_used = session.execute(
                select(func.coalesce(func.sum(UsageRecord.credits_used), 0))
                .join(APIKey, UsageRecord.api_key_id == APIKey.id)
                .where(
                    APIKey.user_id == user.id,
                    UsageRecord.created_at >= period_start,
                )
            ).scalar()

            # Credits used in the last hour
            hourly_used = session.execute(
                select(func.coalesce(func.sum(UsageRecord.credits_used), 0))
                .join(APIKey, UsageRecord.api_key_id == APIKey.id)
                .where(
                    APIKey.user_id == user.id,
                    UsageRecord.created_at >= one_hour_ago,
                )
            ).scalar()

            if total_used <= plan_credits:
                continue  # No overage yet

            # Calculate how much of the hourly usage is overage
            overage_before = max(0, (total_used - hourly_used) - plan_credits)
            overage_now = total_used - plan_credits
            new_overage = overage_now - overage_before
            if new_overage <= 0:
                continue

            try:
                send_meter_event(
                    stripe_customer_id=user.stripe_customer_id,
                    quantity=new_overage,
                    timestamp=int(now.timestamp()),
                )
            except Exception:
                # Log error but don't fail the entire task
                continue
