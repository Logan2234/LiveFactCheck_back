"""Declarative base shared by every ORM model.

Kept in its own module so ``app.db.session`` (engine/init) and the models can both
import it without a circular dependency.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
