"""
Run lock management for scheduled execution.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from procurewatch.persistence.models import RunLock


class LockManager:
    """Manages RunLock rows in database for overlap protection."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def acquire(self, lock_name: str, holder_id: str, ttl_minutes: int = 120) -> bool:
        """Acquire lock. Returns True if acquired, False if held by another."""
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=ttl_minutes)

        stmt = select(RunLock).where(RunLock.lock_name == lock_name)
        lock = self._session.execute(stmt).scalar_one_or_none()

        if lock:
            if lock.expires_at > now and lock.holder_id != holder_id:
                return False

            lock.holder_id = holder_id
            lock.acquired_at = now
            lock.expires_at = expires_at
        else:
            lock = RunLock(
                lock_name=lock_name,
                acquired_at=now,
                expires_at=expires_at,
                holder_id=holder_id,
            )
            self._session.add(lock)

        self._session.commit()
        return True

    def release(self, lock_name: str, holder_id: str) -> bool:
        """Release lock. Returns True if released, False if not held by us."""
        stmt = select(RunLock).where(RunLock.lock_name == lock_name)
        lock = self._session.execute(stmt).scalar_one_or_none()

        if lock is None or lock.holder_id != holder_id:
            return False

        self._session.delete(lock)
        self._session.commit()
        return True

    def is_locked(self, lock_name: str) -> bool:
        """Check if lock is currently held (not expired)."""
        now = datetime.utcnow()
        stmt = select(RunLock).where(RunLock.lock_name == lock_name)
        lock = self._session.execute(stmt).scalar_one_or_none()

        if lock is None:
            return False

        return lock.expires_at > now

    def cleanup_expired(self) -> int:
        """Remove all expired locks. Returns count removed."""
        now = datetime.utcnow()
        stmt = delete(RunLock).where(RunLock.expires_at <= now)
        result = self._session.execute(stmt)
        self._session.commit()
        return int(result.rowcount or 0)
