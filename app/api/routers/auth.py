"""Admin authentication: exchange the admin password for a JWT."""

from fastapi import APIRouter, HTTPException, status

from app.core.security import check_password, create_token
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/admin", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def admin_login(req: LoginRequest) -> TokenResponse:
    if not check_password(req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mot de passe incorrect",
        )
    return TokenResponse(token=create_token())
