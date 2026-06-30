"""Persistence for user accounts.

Synchronous SQLAlchemy helpers that take the request-scoped ``Session`` (from the
``get_db`` dependency), so the routes stay thin and tests can override the DB. Password
hashing happens here so a plaintext password never reaches the model layer.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.passwords import hash_password
from app.models import User
from app.services.session_store import utcnow


def create_user(db: DBSession, *, email: str, username: str, password: str) -> User:
    now = utcnow()
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        username=username,
        password_hash=hash_password(password),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    return user


def get_user(db: DBSession, user_id: str) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: DBSession, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def get_user_by_username(db: DBSession, username: str) -> User | None:
    return db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()


def touch_last_login(db: DBSession, user_id: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        return
    user.last_login_at = utcnow()
    db.commit()


def update_email(db: DBSession, user_id: str, new_email: str) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None
    user.email = new_email
    user.updated_at = utcnow()
    db.commit()
    return user


def update_password(db: DBSession, user_id: str, new_password: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        return
    user.password_hash = hash_password(new_password)
    user.updated_at = utcnow()
    db.commit()


def delete_user(db: DBSession, user_id: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        return
    # Webhooks cascade via the relationship's delete-orphan rule.
    db.delete(user)
    db.commit()
