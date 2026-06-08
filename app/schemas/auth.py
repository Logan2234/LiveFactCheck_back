"""Request/response schemas for the admin auth routes."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    token: str
