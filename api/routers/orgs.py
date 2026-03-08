"""Organisation management endpoints — /v1/orgs."""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func as sa_func

from api.middleware.auth import get_api_key_user, hash_key
from api.models.org import Organisation, OrgMember
from api.models.user import APIKey, User, UsageRecord, PLAN_LIMITS
from api.services.database import get_session

router = APIRouter(prefix="/orgs", tags=["Orgs"])


# ── Request / Response schemas ──────────────────────────────────────────


class CreateOrgRequest(BaseModel):
    name: str
    slug: str


class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str
    monthly_credits: int
    is_active: bool
    members: list[dict] = []


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class CreateOrgKeyRequest(BaseModel):
    name: str = "Org API Key"
    environment: str = "production"


class OrgKeyResponse(BaseModel):
    api_key: str
    prefix: str
    name: str
    environment: str


# ── Helpers ─────────────────────────────────────────────────────────────


async def _get_org_and_check_role(slug: str, user_id: int, min_role: str = "member"):
    """Load org and verify user has at least min_role. Returns (org, member)."""
    role_hierarchy = {"owner": 3, "admin": 2, "member": 1}

    async for session in get_session():
        org = (await session.execute(
            select(Organisation).where(Organisation.slug == slug, Organisation.is_active == True)
        )).scalar_one_or_none()
        if not org:
            raise HTTPException(404, "Organisation not found.")

        member = (await session.execute(
            select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user_id)
        )).scalar_one_or_none()
        if not member:
            raise HTTPException(403, "Not a member of this organisation.")

        if role_hierarchy.get(member.role, 0) < role_hierarchy.get(min_role, 0):
            raise HTTPException(403, f"Requires {min_role} role or higher.")

        return org, member


# ── Endpoints ───────────────────────────────────────────────────────────


@router.post("", status_code=201)
async def create_org(req: CreateOrgRequest, user_info: dict = Depends(get_api_key_user)):
    """Create an organisation. The caller becomes the owner."""
    async for session in get_session():
        existing = (await session.execute(
            select(Organisation).where(Organisation.slug == req.slug)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "Organisation slug already taken.")

        org = Organisation(name=req.name, slug=req.slug)
        session.add(org)
        await session.flush()

        member = OrgMember(org_id=org.id, user_id=user_info["user_id"], role="owner")
        session.add(member)
        await session.commit()

        return {"id": org.id, "name": org.name, "slug": org.slug, "plan": org.plan}


@router.get("/{slug}")
async def get_org(slug: str, user_info: dict = Depends(get_api_key_user)):
    """Get organisation details with member list."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "member")

    async for session in get_session():
        members_result = await session.execute(
            select(OrgMember, User)
            .join(User, OrgMember.user_id == User.id)
            .where(OrgMember.org_id == org.id)
        )
        members = [
            {"user_id": m.user_id, "email": u.email, "name": u.name, "role": m.role}
            for m, u in members_result.all()
        ]

    return OrgResponse(
        id=org.id, name=org.name, slug=org.slug,
        plan=org.plan, monthly_credits=org.monthly_credits,
        is_active=org.is_active, members=members,
    )


@router.post("/{slug}/members", status_code=201)
async def invite_member(slug: str, req: InviteMemberRequest, user_info: dict = Depends(get_api_key_user)):
    """Add a member to the organisation (owner/admin only)."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "admin")

    if req.role not in ("member", "admin"):
        raise HTTPException(422, "Role must be 'member' or 'admin'. Use transfer for owner.")

    async for session in get_session():
        user = (await session.execute(
            select(User).where(User.email == req.email)
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found. They must register first.")

        existing = (await session.execute(
            select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "User is already a member.")

        member = OrgMember(org_id=org.id, user_id=user.id, role=req.role)
        session.add(member)
        await session.commit()

        return {"status": "added", "email": req.email, "role": req.role}


@router.delete("/{slug}/members/{user_id}")
async def remove_member(slug: str, user_id: int, user_info: dict = Depends(get_api_key_user)):
    """Remove a member from the organisation (owner/admin only)."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "admin")

    async for session in get_session():
        member = (await session.execute(
            select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user_id)
        )).scalar_one_or_none()
        if not member:
            raise HTTPException(404, "Member not found.")
        if member.role == "owner":
            raise HTTPException(403, "Cannot remove the owner.")

        await session.delete(member)
        await session.commit()

        return {"status": "removed", "user_id": user_id}


@router.post("/{slug}/keys", response_model=OrgKeyResponse, status_code=201)
async def create_org_key(slug: str, req: CreateOrgKeyRequest, user_info: dict = Depends(get_api_key_user)):
    """Create an API key for the organisation (owner/admin only)."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "admin")

    if req.environment not in ("production", "staging", "development", "test"):
        raise HTTPException(422, "Environment must be production, staging, development, or test.")

    async for session in get_session():
        full_key, prefix = APIKey.generate_key()
        api_key = APIKey(
            user_id=user_info["user_id"],
            org_id=org.id,
            key_prefix=prefix,
            key_hash=hash_key(full_key),
            name=req.name,
            environment=req.environment,
        )
        session.add(api_key)
        await session.commit()

        return OrgKeyResponse(
            api_key=full_key, prefix=prefix,
            name=req.name, environment=req.environment,
        )


@router.get("/{slug}/keys")
async def list_org_keys(slug: str, user_info: dict = Depends(get_api_key_user)):
    """List all API keys for the organisation."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "member")

    async for session in get_session():
        result = await session.execute(
            select(APIKey).where(APIKey.org_id == org.id, APIKey.is_active == True)
        )
        keys = result.scalars().all()

        return [
            {
                "id": k.id,
                "prefix": k.key_prefix,
                "name": k.name,
                "environment": k.environment,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]


@router.get("/{slug}/usage")
async def org_usage(
    slug: str,
    format: str = "json",
    user_info: dict = Depends(get_api_key_user),
):
    """Get organisation usage breakdown by API key and endpoint."""
    org, _ = await _get_org_and_check_role(slug, user_info["user_id"], "member")

    now = datetime.now(timezone.utc)

    async for session in get_session():
        # Aggregate usage for this org's keys
        stmt = (
            select(
                UsageRecord.api_key_id,
                UsageRecord.endpoint,
                sa_func.sum(UsageRecord.credits_used).label("credits"),
                sa_func.count().label("requests"),
            )
            .join(APIKey, UsageRecord.api_key_id == APIKey.id)
            .where(APIKey.org_id == org.id)
            .group_by(UsageRecord.api_key_id, UsageRecord.endpoint)
        )
        rows = (await session.execute(stmt)).all()

        usage_data = []
        for row in rows:
            usage_data.append({
                "api_key_id": row.api_key_id,
                "endpoint": row.endpoint,
                "credits": row.credits,
                "requests": row.requests,
            })

    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["api_key_id", "endpoint", "credits", "requests"])
        writer.writeheader()
        for row in usage_data:
            writer.writerow(row)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=org_usage.csv"},
        )

    return {
        "org": slug,
        "plan": org.plan,
        "monthly_credits": org.monthly_credits,
        "usage": usage_data,
    }
