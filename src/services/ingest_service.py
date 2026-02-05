from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx
import asyncio
import uuid
from src.db.mongo import get_db
from src.services.classify_service import ClassifyService
from src.services.notify_service import NotifyService
from src.services.lock_service import LockService
from src.services.rate_limiter import get_rate_limiter
from src.services.sync_service import SyncService
from src.core.logging import logger


class IngestService:
    def __init__(self):
        self.external_api_url = "http://mock-external-api:9000/external/support-tickets"
        self.classify_service = ClassifyService()
        self.notify_service = NotifyService()
        self.lock_service = LockService()
        self.rate_limiter = get_rate_limiter()
        self.sync_service = SyncService()
        # Track cancellation flags
        self._cancellation_flags: Dict[str, bool] = {}

    async def run_ingestion(self, tenant_id: str) -> dict:
        """
        Fetch tickets from the external API and persist them for a tenant.
        
        Implements:
        - Task 1: Pagination, idempotency, classification, notifications
        - Task 8: Distributed locking with atomic operations
        - Task 9: Job tracking and progress
        - Task 10: Rate limiting
        - Task 12: Change detection and sync
        - Debug Task C: No memory leak (removed _ingestion_cache)
        - Debug Task D: Fixed race condition with atomic lock
        """
        db = await get_db()
        job_id = str(uuid.uuid4())
        
        # ============================================================
        # 🐛 DEBUG TASK D: Fixed race condition
        # Use atomic lock acquisition instead of check-then-act
        # ============================================================
        lock_acquired = await self.lock_service.acquire_lock(
            f"ingest:{tenant_id}",
            job_id
        )
        
        if not lock_acquired:
            # Check if there's a running job
            existing_job = await db.ingestion_jobs.find_one({
                "tenant_id": tenant_id,
                "status": "running"
            })
            
            if existing_job:
                return {
                    "status": "already_running",
                    "job_id": str(existing_job["_id"]),
                    "new_ingested": 0,
                    "updated": 0,
                    "errors": 0
                }
        
        # Record ingestion job start
        job_doc = {
            "tenant_id": tenant_id,
            "status": "running",
            "started_at": datetime.utcnow(),
            "progress": 0,
            "total_pages": None,
            "processed_pages": 0,
            "job_id": job_id
        }
        result = await db.ingestion_jobs.insert_one(job_doc)
        job_db_id = result.inserted_id
        
        # Initialize cancellation flag
        self._cancellation_flags[job_id] = False

        new_ingested = 0
        updated = 0
        errors = 0
        all_external_ids = []

        try:
            # Fetch tickets with pagination
            page = 1
            total_pages = None
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    # Check for cancellation
                    if self._cancellation_flags.get(job_id, False):
                        logger.info(f"Ingestion job {job_id} cancelled")
                        break
                    
                    # Rate limiting: wait if necessary
                    await self.rate_limiter.wait_and_acquire()
                    
                    # Fetch page with retry on 429
                    page_data = await self._fetch_page_with_retry(
                        client, tenant_id, page
                    )
                    
                    if not page_data:
                        break
                    
                    tickets = page_data.get("tickets", [])
                    pagination = page_data.get("pagination", {})
                    total_pages = pagination.get("total_pages", 1)
                    
                    # Update job progress
                    await db.ingestion_jobs.update_one(
                        {"_id": job_db_id},
                        {
                            "$set": {
                                "total_pages": total_pages,
                                "processed_pages": page,
                                "progress": int((page / total_pages) * 100) if total_pages > 0 else 0
                            }
                        }
                    )
                    
                    # Process tickets
                    for ticket_data in tickets:
                        try:
                            external_id = ticket_data.get("id")
                            all_external_ids.append(external_id)
                            
                            # Check for changes (Task 12)
                            sync_result = await self.sync_service.sync_ticket(
                                ticket_data, tenant_id
                            )
                            
                            # Classify ticket
                            classification = self.classify_service.classify(
                                ticket_data.get("message", ""),
                                ticket_data.get("subject", "")
                            )
                            
                            # Parse datetime fields
                            from dateutil import parser as date_parser
                            created_at = ticket_data.get("created_at")
                            updated_at = ticket_data.get("updated_at")
                            
                            if isinstance(created_at, str):
                                created_at = date_parser.parse(created_at)
                            if isinstance(updated_at, str):
                                updated_at = date_parser.parse(updated_at)
                            
                            # Prepare ticket document
                            ticket_doc = {
                                "external_id": external_id,
                                "tenant_id": tenant_id,
                                "source": ticket_data.get("source", ""),
                                "customer_id": ticket_data.get("customer_id", ""),
                                "subject": ticket_data.get("subject", ""),
                                "message": ticket_data.get("message", ""),
                                "created_at": created_at,
                                "updated_at": updated_at,
                                "status": ticket_data.get("status", ""),
                                "urgency": classification["urgency"],
                                "sentiment": classification["sentiment"],
                                "requires_action": classification["requires_action"]
                            }
                            
                            logger.info(f"Upserting ticket {external_id} for tenant {tenant_id}")
                            
                            # Upsert for idempotency
                            upsert_result = await db.tickets.update_one(
                                {
                                    "tenant_id": tenant_id,
                                    "external_id": external_id
                                },
                                {"$set": ticket_doc},
                                upsert=True
                            )
                            
                            if upsert_result.upserted_id:
                                new_ingested += 1
                                # Record creation in history
                                await self.sync_service.record_history(
                                    ticket_id=external_id,
                                    tenant_id=tenant_id,
                                    action="created",
                                    changes=None
                                )
                            elif upsert_result.modified_count > 0:
                                updated += 1
                            
                            # Send notification for high urgency tickets (Task 4)
                            if classification["urgency"] == "high":
                                await self.notify_service.send_notification(
                                    ticket_id=external_id,
                                    tenant_id=tenant_id,
                                    urgency="high",
                                    reason="High urgency ticket detected"
                                )
                        
                        except Exception as e:
                            logger.error(f"Error processing ticket: {str(e)}")
                            errors += 1
                    
                    # Check if we've reached the last page
                    if page >= total_pages:
                        break
                    
                    page += 1
                    
                    # Refresh lock periodically
                    if page % 5 == 0:
                        await self.lock_service.refresh_lock(
                            f"ingest:{tenant_id}",
                            job_id
                        )
            
            # Detect and mark deleted tickets (Task 12)
            deleted_ids = await self.sync_service.detect_deleted_tickets(
                tenant_id, all_external_ids
            )
            if deleted_ids:
                await self.sync_service.mark_deleted(tenant_id, deleted_ids)
            
            # Determine final status
            final_status = "cancelled" if self._cancellation_flags.get(job_id, False) else "completed"
            
            # Update job status
            await db.ingestion_jobs.update_one(
                {"_id": job_db_id},
                {"$set": {"status": final_status, "ended_at": datetime.utcnow()}}
            )
            
            # Log successful completion (Task 6)
            # Determine log status based on errors
            if errors > 0:
                log_status = "PARTIAL_SUCCESS"
            elif final_status == "failed":
                log_status = "FAILED"
            else:
                log_status = "SUCCESS"
                
            await db.ingestion_logs.insert_one({
                "tenant_id": tenant_id,
                "job_id": job_id,
                "status": log_status,
                "started_at": job_doc["started_at"],
                "ended_at": datetime.utcnow(),
                "new_ingested": new_ingested,
                "updated": updated,
                "errors": errors
            })
            
            return {
                "status": final_status,
                "job_id": job_id,
                "new_ingested": new_ingested,
                "updated": updated,
                "errors": errors
            }

        except Exception as e:
            # Log failure (Task 6)
            await db.ingestion_logs.insert_one({
                "tenant_id": tenant_id,
                "job_id": job_id,
                "status": "failed",
                "error": str(e),
                "started_at": job_doc["started_at"],
                "ended_at": datetime.utcnow(),
                "new_ingested": new_ingested,
                "updated": updated,
                "errors": errors
            })
            
            await db.ingestion_jobs.update_one(
                {"_id": job_db_id},
                {"$set": {"status": "failed", "ended_at": datetime.utcnow()}}
            )
            
            raise
        
        finally:
            # Always release the lock
            await self.lock_service.release_lock(
                f"ingest:{tenant_id}",
                job_id
            )
            # Clean up cancellation flag
            self._cancellation_flags.pop(job_id, None)

    async def _fetch_page_with_retry(
        self,
        client: httpx.AsyncClient,
        tenant_id: str,
        page: int,
        max_retries: int = 3
    ) -> Optional[dict]:
        """
        Fetch a page from the external API with retry on 429.
        Implements Task 10: Handle 429 with Retry-After header.
        """
        url = f"{self.external_api_url}?tenant_id={tenant_id}&page={page}"
        
        for attempt in range(max_retries):
            try:
                response = await client.get(url)
                
                if response.status_code == 429:
                    # Rate limited - respect Retry-After header
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited (429). Waiting {retry_after}s before retry")
                    await asyncio.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                return response.json()
            
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    continue
                logger.error(f"HTTP error fetching page {page}: {str(e)}")
                if attempt == max_retries - 1:
                    raise
            except Exception as e:
                logger.error(f"Error fetching page {page}: {str(e)}")
                if attempt == max_retries - 1:
                    raise
            
            # Exponential backoff for other errors
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        
        return None

        # Log successful completion
        await db.ingestion_jobs.update_one(
            {"_id": result.inserted_id},
            {"$set": {"status": "completed", "ended_at": datetime.utcnow()}}
        )

        await db.ingestion_logs.insert_one({
            "tenant_id": tenant_id,
            "job_id": job_id,
            "status": "completed",
            "started_at": job_doc["started_at"],
            "ended_at": datetime.utcnow(),
            "new_ingested": new_ingested,
            "updated": updated,
            "errors": errors
        })

        return {
            "status": "completed",
            "job_id": job_id,
            "new_ingested": new_ingested,
            "updated": updated,
            "errors": errors
        }

    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """Retrieve the status of a specific ingestion job."""
        db = await get_db()

        # Try to find by job_id field first
        job = await db.ingestion_jobs.find_one({"job_id": job_id})
        
        # Fallback to _id if job_id field doesn't exist (backward compatibility)
        if not job:
            try:
                from bson import ObjectId
                if ObjectId.is_valid(job_id):
                    job = await db.ingestion_jobs.find_one({"_id": ObjectId(job_id)})
            except:
                pass
        
        if not job:
            return None

        return {
            "job_id": job.get("job_id", str(job["_id"])),
            "tenant_id": job["tenant_id"],
            "status": job["status"],
            "progress": job.get("progress", 0),
            "total_pages": job.get("total_pages"),
            "processed_pages": job.get("processed_pages", 0),
            "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
            "ended_at": job["ended_at"].isoformat() if job.get("ended_at") else None
        }

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel an ongoing ingestion job, if it is still running."""
        db = await get_db()
        
        # Try to find by job_id field first
        job = await db.ingestion_jobs.find_one({"job_id": job_id, "status": "running"})
        
        # Fallback to _id
        if not job:
            try:
                from bson import ObjectId
                if ObjectId.is_valid(job_id):
                    job = await db.ingestion_jobs.find_one({"_id": ObjectId(job_id), "status": "running"})
            except:
                pass
        
        if not job:
            return False
        
        # Set cancellation flag
        self._cancellation_flags[job.get("job_id", job_id)] = True
        
        return True

    async def get_ingestion_status(self, tenant_id: str) -> Optional[dict]:
        """Get the current ingestion status for a given tenant."""
        db = await get_db()

        job = await db.ingestion_jobs.find_one(
            {"tenant_id": tenant_id, "status": "running"},
            sort=[("started_at", -1)]
        )

        if not job:
            return None

        return {
            "job_id": job.get("job_id", str(job["_id"])),
            "tenant_id": tenant_id,
            "status": job["status"],
            "started_at": job["started_at"].isoformat() if job.get("started_at") else None
        }
