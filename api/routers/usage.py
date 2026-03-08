"""Enhanced usage history endpoint with date range, grouping, filtering, and CSV export."""

import csv
import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func, cast, Date, Integer, case

from api.middleware.auth import get_api_key_user
from api.models.user import UsageRecord, APIKey
from api.services.database import get_session

router = APIRouter(prefix="/usage", tags=["Usage"])


class EndpointBreakdown(BaseModel):
    credits: int
    requests: int
    cached_pct: float


class UsagePeriod(BaseModel):
    period: str
    total_credits: int
    requests: int
    by_endpoint: dict[str, EndpointBreakdown]
    avg_response_ms: float


class UsageHistoryResponse(BaseModel):
    usage: list[UsagePeriod]
    total_credits: int
    total_requests: int
    period: dict[str, str]


def _trunc_expr(group_by: str):
    """Return a SQLAlchemy expression that truncates created_at to the requested period."""
    if group_by == "hour":
        return sa_func.date_trunc("hour", UsageRecord.created_at)
    elif group_by == "week":
        return sa_func.date_trunc("week", UsageRecord.created_at)
    elif group_by == "month":
        return sa_func.date_trunc("month", UsageRecord.created_at)
    # default: day
    return cast(UsageRecord.created_at, Date)


@router.get("/history")
async def usage_history(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_by: str = Query("day", pattern="^(hour|day|week|month)$"),
    endpoint: str | None = Query(None),
    api_key_id: int | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    user_info: dict = Depends(get_api_key_user),
):
    """Return usage history with date range filtering, grouping, and optional CSV export."""

    async for session in get_session():
        # Base filters: only this user's keys
        filters = [APIKey.user_id == user_info["user_id"]]

        if date_from:
            filters.append(UsageRecord.created_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc))
        if date_to:
            # Include the full end day
            end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc)
            filters.append(UsageRecord.created_at <= end)
        if endpoint:
            filters.append(UsageRecord.endpoint == endpoint)
        if api_key_id:
            filters.append(UsageRecord.api_key_id == api_key_id)

        period_col = _trunc_expr(group_by).label("period")

        stmt = (
            select(
                period_col,
                UsageRecord.endpoint,
                sa_func.sum(UsageRecord.credits_used).label("credits"),
                sa_func.count().label("requests"),
                sa_func.sum(case((UsageRecord.cached == True, 1), else_=0)).label("cached_count"),
                sa_func.avg(UsageRecord.response_time_ms).label("avg_ms"),
            )
            .join(APIKey, UsageRecord.api_key_id == APIKey.id)
            .where(*filters)
            .group_by(period_col, UsageRecord.endpoint)
            .order_by(period_col)
        )

        rows = (await session.execute(stmt)).all()

    # Aggregate into grouped periods
    periods: dict[str, dict] = {}
    for row in rows:
        p = str(row.period)[:10] if group_by == "day" else str(row.period)
        if p not in periods:
            periods[p] = {"period": p, "total_credits": 0, "requests": 0, "by_endpoint": {}, "ms_sum": 0.0, "ms_count": 0}
        bucket = periods[p]
        credits = int(row.credits or 0)
        requests = int(row.requests or 0)
        cached = int(row.cached_count or 0)
        avg_ms = float(row.avg_ms or 0)
        cached_pct = round((cached / requests * 100) if requests else 0, 1)

        bucket["total_credits"] += credits
        bucket["requests"] += requests
        bucket["ms_sum"] += avg_ms * requests
        bucket["ms_count"] += requests
        bucket["by_endpoint"][row.endpoint] = {
            "credits": credits,
            "requests": requests,
            "cached_pct": cached_pct,
        }

    usage_list = []
    grand_credits = 0
    grand_requests = 0
    for bucket in periods.values():
        avg_response = round(bucket["ms_sum"] / bucket["ms_count"], 1) if bucket["ms_count"] else 0
        usage_list.append(UsagePeriod(
            period=bucket["period"],
            total_credits=bucket["total_credits"],
            requests=bucket["requests"],
            by_endpoint={k: EndpointBreakdown(**v) for k, v in bucket["by_endpoint"].items()},
            avg_response_ms=avg_response,
        ))
        grand_credits += bucket["total_credits"]
        grand_requests += bucket["requests"]

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "endpoint", "credits", "requests", "cached_pct", "avg_response_ms"])
        for period_item in usage_list:
            for ep_name, ep_data in period_item.by_endpoint.items():
                writer.writerow([
                    period_item.period,
                    ep_name,
                    ep_data.credits,
                    ep_data.requests,
                    ep_data.cached_pct,
                    period_item.avg_response_ms,
                ])
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=usage_export.csv"},
        )

    return UsageHistoryResponse(
        usage=usage_list,
        total_credits=grand_credits,
        total_requests=grand_requests,
        period={
            "from": str(date_from) if date_from else "",
            "to": str(date_to) if date_to else "",
        },
    )
