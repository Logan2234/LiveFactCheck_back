"""User account routes: signup, login (email or username), and self lookup.

Self-service accounts (distinct from the single admin). Signup/login are public;
``/me`` is gated by ``require_user``. Handlers are plain ``def`` so FastAPI runs them in
its threadpool — the sync DB session and the argon2 hash never block the event loop.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.core.passwords import verify_password
from app.core.rate_limit import LoginRateLimiter
from app.core.security import create_user_token
from app.db.session import get_db
from app.dependencies import require_user
from app.schemas.auth import TokenResponse
from app.schemas.user import (
    DeleteAccountRequest,
    SignupRequest,
    UpdateEmailRequest,
    UpdatePasswordRequest,
    UserLoginRequest,
    UserOut,
)
from app.services import user_store

router = APIRouter(prefix="/users", tags=["users"])

# Same brute-force protection as /admin/login, with its own per-IP counter.
_login_limiter = LoginRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, db: DBSession = Depends(get_db)) -> UserOut:
    if user_store.get_user_by_email(db, req.email) is not None:
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    if user_store.get_user_by_username(db, req.username) is not None:
        raise HTTPException(status_code=409, detail="Nom d'utilisateur déjà pris")
    user = user_store.create_user(
        db, email=req.email, username=req.username, password=req.password
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    req: UserLoginRequest, request: Request, db: DBSession = Depends(get_db)
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    if _login_limiter.is_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives, réessayez plus tard",
        )

    user = user_store.get_user_by_email(
        db, req.identifier
    ) or user_store.get_user_by_username(db, req.identifier)
    # One generic 401 for missing/inactive/wrong-password, so the response doesn't
    # reveal whether the identifier exists.
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, req.password)
    ):
        _login_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
        )

    _login_limiter.reset(client_ip)
    user_store.touch_last_login(db, user.id)
    return TokenResponse(token=create_user_token(user.id))


@router.get("/me", response_model=UserOut)
def me(
    user_id: str = Depends(require_user), db: DBSession = Depends(get_db)
) -> UserOut:
    user = user_store.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return UserOut.model_validate(user)


def _reauth(db: DBSession, user_id: str, password: str):
    """Load the signed-in user and re-confirm their password before a sensitive change.

    A valid token proves the session; re-typing the password proves intent. A wrong
    password is 403 (forbidden action), kept distinct from the 401 a bad/expired token
    yields so the client doesn't treat it as a logged-out state.
    """
    user = user_store.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if not verify_password(user.password_hash, password):
        raise HTTPException(status_code=403, detail="Mot de passe incorrect")
    return user


@router.patch("/me/email", response_model=UserOut)
def update_email(
    req: UpdateEmailRequest,
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> UserOut:
    _reauth(db, user_id, req.password)
    existing = user_store.get_user_by_email(db, req.new_email)
    if existing is not None and existing.id != user_id:
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    user = user_store.update_email(db, user_id, req.new_email)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return UserOut.model_validate(user)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def update_password(
    req: UpdatePasswordRequest,
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> None:
    _reauth(db, user_id, req.current_password)
    user_store.update_password(db, user_id, req.new_password)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    req: DeleteAccountRequest,
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> None:
    _reauth(db, user_id, req.password)
    user_store.delete_user(db, user_id)
