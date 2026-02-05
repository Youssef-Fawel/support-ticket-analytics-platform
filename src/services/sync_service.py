"""
Task 12: Data synchronization service.

Responsible for synchronizing ticket data with the external API.

Requirements:
1. Use the ticket `updated_at` field to update only tickets that have changed.
2. Apply soft delete (`deleted_at` field) for tickets deleted in the external system.
3. Record change history in the `ticket_history` collection.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from src.db.mongo import get_db


class SyncService:
    """
    Data synchronization service.
    """

    HISTORY_COLLECTION = "ticket_history"

    async def sync_ticket(self, external_ticket: dict, tenant_id: str) -> dict:
        """
        Synchronize a single ticket.

        Args:
            external_ticket: Ticket payload from the external API.
            tenant_id: Tenant identifier.

        Returns:
            {
                "action": "created" | "updated" | "unchanged",
                "ticket_id": str,
                "changes": List[str]  # list of changed fields
            }

        Uses updated_at to decide whether an update is needed.
        Records field-level changes in history.
        """
        db = await get_db()
        external_id = external_ticket.get("id")
        external_updated_at = external_ticket.get("updated_at")
        
        # Look up existing ticket
        existing = await db.tickets.find_one({
            "tenant_id": tenant_id,
            "external_id": external_id
        })
        
        if not existing:
            # New ticket - create it
            return {
                "action": "created",
                "ticket_id": external_id,
                "changes": []
            }
        
        # Check if ticket has been updated externally
        existing_updated_at = existing.get("updated_at")
        
        # Parse and compare timestamps if they exist
        if external_updated_at and existing_updated_at:
            if isinstance(external_updated_at, str):
                from dateutil import parser as date_parser
                external_updated_at = date_parser.parse(external_updated_at)
            if isinstance(existing_updated_at, str):
                from dateutil import parser as date_parser
                existing_updated_at = date_parser.parse(existing_updated_at)
            
            # Make both timezone-naive or both timezone-aware for comparison
            if external_updated_at.tzinfo is not None and existing_updated_at.tzinfo is None:
                existing_updated_at = existing_updated_at.replace(tzinfo=external_updated_at.tzinfo)
            elif external_updated_at.tzinfo is None and existing_updated_at.tzinfo is not None:
                external_updated_at = external_updated_at.replace(tzinfo=existing_updated_at.tzinfo)
            
            # If external version is not newer, skip update
            if external_updated_at <= existing_updated_at:
                return {
                    "action": "unchanged",
                    "ticket_id": external_id,
                    "changes": []
                }
        
        # Compute field-level changes (exclude updated_at as it was already compared)
        fields_to_compare = ["subject", "message", "status"]
        changes_dict = self.compute_changes(existing, external_ticket, fields_to_compare)
        
        if changes_dict:
            # Record history
            await self.record_history(
                ticket_id=external_id,
                tenant_id=tenant_id,
                action="updated",
                changes=changes_dict
            )
            
            return {
                "action": "updated",
                "ticket_id": external_id,
                "changes": list(changes_dict.keys())
            }
        else:
            # No changes detected
            return {
                "action": "unchanged",
                "ticket_id": external_id,
                "changes": []
            }
        
        return {
            "action": "unchanged",
            "ticket_id": external_id,
            "changes": []
        }

    async def mark_deleted(self, tenant_id: str, external_ids: List[str]) -> int:
        """
        Handle tickets that were deleted in the external system (soft delete).

        Args:
            tenant_id: Tenant identifier.
            external_ids: List of external ticket IDs that have been deleted.

        Returns:
            Number of tickets that were soft-deleted.

        Sets the deleted_at field and records a history entry.
        """
        db = await get_db()
        
        if not external_ids:
            return 0
        
        now = datetime.utcnow()
        
        # Update tickets to mark as deleted
        result = await db.tickets.update_many(
            {
                "tenant_id": tenant_id,
                "external_id": {"$in": external_ids},
                "deleted_at": {"$exists": False}  # Only if not already deleted
            },
            {
                "$set": {"deleted_at": now}
            }
        )
        
        # Record history for each deleted ticket
        for external_id in external_ids:
            await self.record_history(
                ticket_id=external_id,
                tenant_id=tenant_id,
                action="deleted",
                changes=None
            )
        
        return result.modified_count

    async def detect_deleted_tickets(self, tenant_id: str, external_ids: List[str]) -> List[str]:
        """
        Detect tickets that appear to have been deleted externally.

        Finds tickets that exist in our DB but are missing from `external_ids`.

        Args:
            tenant_id: Tenant identifier.
            external_ids: Complete list of ticket IDs from the external API.

        Returns:
            List of external IDs that are presumed deleted.
        """
        db = await get_db()
        
        # Find all tickets for this tenant that are not in the external list
        # and have not been soft-deleted already
        cursor = db.tickets.find(
            {
                "tenant_id": tenant_id,
                "external_id": {"$nin": external_ids},
                "deleted_at": {"$exists": False}
            },
            {"external_id": 1}
        )
        
        deleted_tickets = await cursor.to_list(length=None)
        return [ticket["external_id"] for ticket in deleted_tickets]

    async def record_history(
        self,
        ticket_id: str,
        tenant_id: str,
        action: str,
        changes: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a change history entry.

        Args:
            ticket_id: Ticket identifier.
            tenant_id: Tenant identifier.
            action: "created" | "updated" | "deleted".
            changes: Change details (field -> {old: ..., new: ...}).

        Returns:
            ID of the created history document.
        """
        db = await get_db()

        history_doc = {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "action": action,
            "changes": changes or {},
            "recorded_at": datetime.utcnow()
        }

        result = await db[self.HISTORY_COLLECTION].insert_one(history_doc)
        return str(result.inserted_id)

    async def get_ticket_history(
        self,
        ticket_id: str,
        tenant_id: str,
        limit: int = 50
    ) -> List[dict]:
        """
        Retrieve ticket change history.

        Args:
            ticket_id: Ticket identifier.
            tenant_id: Tenant identifier.
            limit: Maximum number of records to return.

        Returns:
            List of history entries in reverse chronological order.
        """
        db = await get_db()

        cursor = db[self.HISTORY_COLLECTION].find(
            {"ticket_id": ticket_id, "tenant_id": tenant_id}
        ).sort("recorded_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    def compute_changes(self, old_doc: dict, new_doc: dict, fields: List[str]) -> Dict[str, Any]:
        """
        Compute field-level differences between two documents.

        Args:
            old_doc: Previous version of the document.
            new_doc: New version of the document.
            fields: List of fields to compare.

        Returns:
            A mapping of changed fields to their before/after values:
            {
                "field_name": {"old": ..., "new": ...},
                ...
            }
        """
        changes = {}

        for field in fields:
            old_value = old_doc.get(field)
            new_value = new_doc.get(field)

            # Only consider it a change if BOTH exist and differ, or if one exists and the other is explicitly set to something different
            # Ignore cases where both are None/missing
            if old_value is None and new_value is None:
                continue
            
            if old_value != new_value:
                changes[field] = {
                    "old": old_value,
                    "new": new_value
                }

        return changes
