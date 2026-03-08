"""User registration and API key management endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from api.services.database import get_session
from api.models.user import User, APIKey
from api.middleware.auth import hash_key, get_api_key_user

import bcrypt

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class RegisterResponse(BaseModel):
    user_id: int
    email: str
    plan: str
    api_key: str


class APIKeyResponse(BaseModel):
    api_key: str
    prefix: str
    name: str


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(req: RegisterRequest):
    """Create a new user account and return an API key.

    The API key is shown only once — store it securely.
    """
    async for session in get_session():
        # Check if email already exists
        existing = await session.execute(
            select(User).where(User.email == req.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered.")

        # Create user
        password_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
        user = User(
            email=req.email,
            password_hash=password_hash,
            name=req.name or req.email,
            plan="free",
        )
        session.add(user)
        await session.flush()  # Get user.id

        # Generate API key
        full_key, prefix = APIKey.generate_key()
        api_key = APIKey(
            user_id=user.id,
            key_prefix=prefix,
            key_hash=hash_key(full_key),
            name="Default",
        )
        session.add(api_key)
        await session.commit()

        return RegisterResponse(
            user_id=user.id,
            email=user.email,
            plan="free",
            api_key=full_key,
        )


@router.post("/keys", response_model=APIKeyResponse, status_code=201)
async def create_api_key(
    user_info: dict = Depends(get_api_key_user),
):
    """Generate an additional API key for the authenticated user."""
    async for session in get_session():
        full_key, prefix = APIKey.generate_key()
        api_key = APIKey(
            user_id=user_info["user_id"],
            key_prefix=prefix,
            key_hash=hash_key(full_key),
            name="Additional key",
        )
        session.add(api_key)
        await session.commit()

        return APIKeyResponse(
            api_key=full_key,
            prefix=prefix,
            name=api_key.name,
        )


@router.delete("/keys/{key_prefix}")
async def revoke_api_key(
    key_prefix: str,
    user_info: dict = Depends(get_api_key_user),
):
    """Revoke an API key by its prefix."""
    async for session in get_session():
        result = await session.execute(
            select(APIKey).where(
                APIKey.user_id == user_info["user_id"],
                APIKey.key_prefix == key_prefix,
                APIKey.is_active == True,
            )
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found.")

        api_key.is_active = False
        await session.commit()

        return {"status": "revoked", "prefix": key_prefix}
