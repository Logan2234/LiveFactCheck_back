"""Test configuration shared by the whole suite.

Importing ``app.config`` builds ``Settings`` and instantiates the Anthropic
client at module load, and the ANTHROPIC_API_KEY validator rejects a missing or
placeholder key. We set dummy env vars here — before any ``app`` import — so the
suite runs offline without a real .env. No network call is made at import time.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-a-placeholder")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
