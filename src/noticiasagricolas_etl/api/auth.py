"""API key validation, tier checking, and rate limiting.

Keys stored in SQLite. Free tier = no key, rate limited by IP.
"""

import hashlib
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import DATA_DIR

AUTH_DB_PATH = DATA_DIR / "auth.db"

bearer_scheme = HTTPBearer(auto_error=False)


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


TIER_LIMITS = {
    Tier.FREE: {
        "prices_per_day": 100,
        "analytics_per_day": 10,
        "max_rows": 100,
        "history_years": 1,
        "csv_export": False,
    },
    Tier.PRO: {
        "prices_per_day": 5000,
        "analytics_per_day": 1000,
        "max_rows": 5000,
        "history_years": None,  # full
        "csv_export": True,
    },
    Tier.ENTERPRISE: {
        "prices_per_day": 50000,
        "analytics_per_day": 10000,
        "max_rows": 50000,
        "history_years": None,
        "csv_export": True,
    },
}


def _init_db():
    """Create auth SQLite database if needed."""
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(AUTH_DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash TEXT PRIMARY KEY,
                key_prefix TEXT NOT NULL,
                name TEXT,
                tier TEXT NOT NULL DEFAULT 'free',
                created_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                key_hash TEXT,
                endpoint_type TEXT,
                timestamp REAL,
                ip_address TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_ts
            ON usage_log(key_hash, endpoint_type, timestamp)
        """)


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_api_key(name: str, tier: str = "free") -> str:
    """Create a new API key. Returns the raw key (only shown once)."""
    import secrets
    raw_key = f"na_live_{secrets.token_hex(24)}"
    key_hash = _hash_key(raw_key)
    _init_db()
    with sqlite3.connect(str(AUTH_DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO api_keys (key_hash, key_prefix, name, tier, created_at) VALUES (?, ?, ?, ?, ?)",
            (key_hash, raw_key[:12], name, tier, time.time()),
        )
    return raw_key


def validate_key(api_key: str) -> dict | None:
    """Validate an API key. Returns key info dict or None."""
    _init_db()
    key_hash = _hash_key(api_key)
    with sqlite3.connect(str(AUTH_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND active = 1",
            (key_hash,),
        ).fetchone()
    if row:
        return dict(row)
    return None


# ── In-memory rate limiter (sliding window) ──────────────────────────

@dataclass
class _RateLimiter:
    windows: dict = field(default_factory=lambda: defaultdict(list))

    def check(self, key: str, limit: int, window_seconds: int = 86400) -> bool:
        """Return True if within limit, False if exceeded."""
        now = time.time()
        cutoff = now - window_seconds
        entries = [t for t in self.windows.get(key, []) if t > cutoff]
        if len(entries) >= limit:
            self.windows[key] = entries
            return False
        entries.append(now)
        self.windows[key] = entries
        return True

    def remaining(self, key: str, limit: int, window_seconds: int = 86400) -> int:
        now = time.time()
        cutoff = now - window_seconds
        entries = [t for t in self.windows.get(key, []) if t > cutoff]
        if entries:
            self.windows[key] = entries
        elif key in self.windows:
            del self.windows[key]
        return max(0, limit - len(entries))


_limiter = _RateLimiter()


@dataclass
class AuthContext:
    tier: Tier = Tier.FREE
    key_hash: str | None = None
    ip: str | None = None
    limits: dict = field(default_factory=dict)

    def __post_init__(self):
        self.limits = TIER_LIMITS.get(self.tier, TIER_LIMITS[Tier.FREE])


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    """Extract auth context from request. Free tier if no key provided."""
    if credentials and credentials.credentials:
        key_info = validate_key(credentials.credentials)
        if key_info is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        tier = Tier(key_info["tier"])
        return AuthContext(tier=tier, key_hash=key_info["key_hash"], ip=request.client.host)

    # Free tier by IP
    return AuthContext(tier=Tier.FREE, ip=request.client.host if request.client else "unknown")


def check_rate_limit(auth: AuthContext, endpoint_type: str = "prices"):
    """Check rate limit for the given auth context and endpoint type.

    Raises HTTPException(429) if limit exceeded.
    """
    limit_key = f"{endpoint_type}_per_day"
    limit = auth.limits.get(limit_key)
    if limit is None:
        return

    rate_key = f"{auth.key_hash or auth.ip}:{endpoint_type}"
    if not _limiter.check(rate_key, limit):
        remaining = _limiter.remaining(rate_key, limit)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. {remaining} {endpoint_type} requests remaining today.",
            headers={"Retry-After": "3600"},
        )
