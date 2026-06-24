"""Database layer: engine, session factory and the declarative base.

Cross-cutting infrastructure (see .claude/rules/architecture.md). ORM models live
in ``app/models/``; this package only owns the connection and the ``Base`` they
inherit from.
"""
