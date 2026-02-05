"""
Task 8: Distributed lock service.

Implement a distributed lock using MongoDB atomic operations.
Do not use external distributed lock libraries (redis-lock, pottery, etc.).

Requirements:
1. Prevent concurrent ingestion for the same tenant.
2. Return 409 Conflict when lock acquisition fails.
3. Automatically release locks when they are not refreshed within 60 seconds (zombie lock prevention).
4. Provide lock status inspection APIs.
"""

from datetime import datetime, timedelta
from typing import Optional
from src.db.mongo import get_db


class LockService:
    """
    MongoDB-based distributed lock service.

    Hints:
    - Use `findOneAndUpdate` with `upsert` to acquire locks.
    - Use TTL-like behaviour for automatic expiration.
    - Acquire/release locks atomically.
    """

    LOCK_COLLECTION = "distributed_locks"
    LOCK_TTL_SECONDS = 60

    async def acquire_lock(self, resource_id: str, owner_id: str) -> bool:
        """
        Attempt to acquire a lock.

        Args:
            resource_id: ID of the resource to lock (e.g., tenant_id).
            owner_id: Lock owner identifier (e.g., job_id).

        Returns:
            True if lock acquired, False otherwise.

        Uses atomic operations to prevent race conditions.
        Strategy: Try update first (expired lock), then insert (new lock).
        """
        db = await get_db()
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self.LOCK_TTL_SECONDS)

        # Strategy 1: Try to atomically update an expired lock
        # This uses find_one_and_update which is atomic and prevents race conditions
        result = await db[self.LOCK_COLLECTION].find_one_and_update(
            {
                "resource_id": resource_id,
                "expires_at": {"$lt": now}  # Only acquire if expired
            },
            {
                "$set": {
                    "owner_id": owner_id,
                    "acquired_at": now,
                    "expires_at": expires_at
                }
            },
            return_document=True
        )
        
        if result is not None:
            return True

        # Strategy 2: Try to insert a new lock (if none exists for this resource)
        # The unique index on resource_id ensures only ONE insert succeeds
        try:
            await db[self.LOCK_COLLECTION].insert_one({
                "resource_id": resource_id,
                "owner_id": owner_id,
                "acquired_at": now,
                "expires_at": expires_at
            })
            return True
        except Exception as e:
            # If insert failed due to duplicate key (lock exists), lock is held
            # DuplicateKeyError means another process holds the lock
            from pymongo.errors import DuplicateKeyError
            if not isinstance(e, DuplicateKeyError):
                # Unexpected error - re-raise it
                raise
            # Lock exists and is not expired - acquisition failed
            return False

    async def release_lock(self, resource_id: str, owner_id: str) -> bool:
        """
        Release a lock.

        Args:
            resource_id: ID of the resource to unlock.
            owner_id: Lock owner identifier (only the owner may release).

        Returns:
            True if lock released, False otherwise.

        Only releases the lock when owner_id matches the stored owner.
        """
        db = await get_db()
        
        result = await db[self.LOCK_COLLECTION].delete_one({
            "resource_id": resource_id,
            "owner_id": owner_id
        })
        
        return result.deleted_count > 0

    async def refresh_lock(self, resource_id: str, owner_id: str) -> bool:
        """
        Refresh a lock's TTL to prevent expiration.

        Args:
            resource_id: ID of the lock to refresh.
            owner_id: Lock owner identifier.

        Returns:
            True if lock refreshed, False otherwise.

        For long-running jobs, call this periodically to keep the lock alive.
        """
        db = await get_db()
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self.LOCK_TTL_SECONDS)
        
        result = await db[self.LOCK_COLLECTION].update_one(
            {
                "resource_id": resource_id,
                "owner_id": owner_id
            },
            {
                "$set": {
                    "expires_at": expires_at
                }
            }
        )
        
        return result.modified_count > 0

    async def get_lock_status(self, resource_id: str) -> Optional[dict]:
        """
        Get current lock status for a resource.

        Returns:
            A dict describing the lock or None if no lock exists:
            {
                "resource_id": str,
                "owner_id": str,
                "acquired_at": datetime,
                "expires_at": datetime,
                "is_expired": bool
            }
        """
        db = await get_db()
        lock = await db[self.LOCK_COLLECTION].find_one({"resource_id": resource_id})

        if not lock:
            return None

        now = datetime.utcnow()
        expires_at = lock.get("expires_at", now)

        return {
            "resource_id": lock["resource_id"],
            "owner_id": lock["owner_id"],
            "acquired_at": lock.get("acquired_at"),
            "expires_at": expires_at,
            "is_expired": now > expires_at
        }

    async def cleanup_expired_locks(self) -> int:
        """
        Clean up expired locks (optional helper).

        Returns:
            Number of deleted locks.
        """
        db = await get_db()
        result = await db[self.LOCK_COLLECTION].delete_many({
            "expires_at": {"$lt": datetime.utcnow()}
        })
        return result.deleted_count
