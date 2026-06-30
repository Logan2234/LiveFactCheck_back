"""Request/response schemas for the user account routes."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8)


class UserLoginRequest(BaseModel):
    # Accepts an email or a username — resolved server-side.
    identifier: str
    password: str


class UpdateEmailRequest(BaseModel):
    # The current password re-confirms identity before a sensitive change.
    new_email: EmailStr
    password: str


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class DeleteAccountRequest(BaseModel):
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    is_active: bool
    created_at: datetime
