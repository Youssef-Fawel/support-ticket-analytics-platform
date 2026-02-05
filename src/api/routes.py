from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Optional
from datetime import datetime
from src.db.models import TicketResponse, TenantStats, TicketListResponse
from src.db.mongo import get_db
from src.services.ingest_service import IngestService
from src.services.analytics_service import AnalyticsService
from src.services.lock_service import LockService
from src.services.circuit_breaker import get_circuit_breaker

router = APIRouter()


# ============================================================
# Ticket APIs
# ============================================================

@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    tenant_id: str,
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    source: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    db = await get_db()
    
    # ============================================================
    # ✅ DEBUG TASK A FIXED: Added tenant_id scoping and soft-delete filter
    # ============================================================
    query: dict = {
        "tenant_id": tenant_id,  # Always filter by tenant
        "deleted_at": {"$exists": False}  # Exclude soft-deleted tickets
    }
    
    if status:
        query["status"] = status
    if urgency:
        query["urgency"] = urgency
    if source:
        query["source"] = source

    cursor = db.tickets.find(query).skip((page - 1) * page_size).limit(page_size)
    docs = await cursor.to_list(length=page_size)
    
    # Convert MongoDB docs to response format
    for doc in docs:
        if "_id" in doc:
            doc["id"] = str(doc["_id"])
            del doc["_id"]
    
    return {"tickets": docs}


@router.get("/tickets/urgent", response_model=TicketListResponse)
async def list_urgent_tickets(tenant_id: str):
    db = await get_db()
    
    query = {
        "tenant_id": tenant_id,
        "urgency": "high",
        "deleted_at": {"$exists": False}
    }
    
    cursor = db.tickets.find(query).sort("created_at", -1).limit(100)
    docs = await cursor.to_list(length=100)
    
    # Convert MongoDB docs
    for doc in docs:
        if "_id" in doc:
            doc["id"] = str(doc["_id"])
            del doc["_id"]
    
    return {"tickets": docs}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, tenant_id: str):
    db = await get_db()
    
    ticket = await db.tickets.find_one({
        "external_id": ticket_id,
        "tenant_id": tenant_id,
        "deleted_at": {"$exists": False}
    })
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Convert _id to string
    if "_id" in ticket:
        ticket["id"] = str(ticket["_id"])
        del ticket["_id"]
    
    return ticket


# ============================================================
# Health Check API (Task 5)
# ============================================================

@router.get("/health")
async def health_check():
    """
    System health check with dependency validation (Task 5).
    
    Returns:
    - 200 OK if all dependencies are healthy
    - 503 Service Unavailable if any dependency is down
    """
    import httpx
    
    health_status = {
        "status": "ok",
        "dependencies": {}
    }
    
    all_healthy = True
    
    # Check MongoDB
    try:
        db = await get_db()
        await db.command("ping")
        health_status["dependencies"]["mongodb"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["mongodb"] = f"unhealthy: {str(e)}"
        all_healthy = False
    
    # Check External API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://mock-external-api:9000/health")
            if response.status_code == 200:
                health_status["dependencies"]["external_api"] = "healthy"
            else:
                health_status["dependencies"]["external_api"] = f"unhealthy: status {response.status_code}"
                all_healthy = False
    except Exception as e:
        health_status["dependencies"]["external_api"] = f"unhealthy: {str(e)}"
        all_healthy = False
    
    if not all_healthy:
        health_status["status"] = "degraded"
        return JSONResponse(
            status_code=503,
            content=health_status
        )
    
    return health_status


# ============================================================
# Analytics API (Task 3)
# ============================================================

@router.get("/tenants/{tenant_id}/stats", response_model=TenantStats)
async def get_tenant_stats(
    tenant_id: str,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    analytics_service: AnalyticsService = Depends()
):
    """
    Retrieve analytics and statistics for a given tenant.

    TODO: Implement using MongoDB's Aggregation Pipeline:
    - Avoid Python for-loops over large result sets.
    - Ensure it can respond within ~500ms for 10,000+ tickets.
    """
    return await analytics_service.get_tenant_stats(tenant_id, from_date, to_date)


# ============================================================
# Ingestion APIs (Task 1, 8, 9)
# ============================================================

@router.post("/ingest/run")
async def run_ingestion(
    tenant_id: str,
    background_tasks: BackgroundTasks,
    ingest_service: IngestService = Depends()
):
    """
    Trigger a ticket ingestion run for a tenant.
    
    Task 8: Distributed locking prevents concurrent ingestion.
    Task 9: Returns job_id for progress tracking.
    
    Returns 409 Conflict if ingestion is already running for this tenant.
    """
    # The lock is now handled inside ingest_service.run_ingestion()
    # which uses atomic operations to prevent race conditions
    result = await ingest_service.run_ingestion(tenant_id)
    
    # If already running, return 409
    if result.get("status") == "already_running":
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running for tenant {tenant_id}",
            headers={"X-Job-ID": result.get("job_id", "")}
        )
    
    return result


@router.get("/ingest/status")
async def get_ingestion_status(
    tenant_id: str,
    ingest_service: IngestService = Depends()
):
    """
    Get the current ingestion status for the given tenant (Task 8).

    Returns the current ingestion job state for this tenant.
    """
    status = await ingest_service.get_ingestion_status(tenant_id)
    if not status:
        return {"status": "idle", "tenant_id": tenant_id}
    return status


@router.get("/ingest/progress/{job_id}")
async def get_ingestion_progress(
    job_id: str,
    ingest_service: IngestService = Depends()
):
    """
    Retrieve ingestion job progress by `job_id` (Task 9).

    TODO: Implement:
    - Look up the job by `job_id`.
    - Return progress information (e.g., total_pages, processed_pages, status).
    """
    status = await ingest_service.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@router.delete("/ingest/{job_id}")
async def cancel_ingestion(
    job_id: str,
    ingest_service: IngestService = Depends()
):
    """
    Cancel a running ingestion job (Task 9).

    TODO: Implement graceful cancellation:
    - Stop further processing while keeping already ingested data.
    """
    success = await ingest_service.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already completed")
    return {"status": "cancelled", "job_id": job_id}


# ============================================================
# Lock Status API (Task 8)
# ============================================================

@router.get("/ingest/lock/{tenant_id}")
async def get_lock_status(tenant_id: str):
    """
    Get the current ingestion lock status for a tenant (Task 8).
    """
    lock_service = LockService()
    status = await lock_service.get_lock_status(f"ingest:{tenant_id}")
    if not status:
        return {"locked": False, "tenant_id": tenant_id}
    return {"locked": not status["is_expired"], **status}


# ============================================================
# Circuit Breaker Status API (Task 11)
# ============================================================

@router.get("/circuit/{name}/status")
async def get_circuit_status(name: str):
    """
    Get the current status of a Circuit Breaker instance (Task 11).

    Example: `GET /circuit/notify/status`.
    """
    cb = get_circuit_breaker(name)
    return cb.get_status()


@router.post("/circuit/{name}/reset")
async def reset_circuit(name: str):
    """
    Reset the Circuit Breaker state (for debugging/testing).
    """
    cb = get_circuit_breaker(name)
    cb.reset()
    return {"status": "reset", "name": name}


# ============================================================
# Ticket History API (Task 12)
# ============================================================

@router.get("/tickets/{ticket_id}/history")
async def get_ticket_history(
    ticket_id: str,
    tenant_id: str,
    limit: int = Query(50, ge=1, le=200)
):
    """
    Retrieve the change history for a ticket (Task 12).
    """
    from src.services.sync_service import SyncService
    sync_service = SyncService()
    history = await sync_service.get_ticket_history(ticket_id, tenant_id, limit)
    
    # Convert ObjectId to string to avoid serialization error
    for doc in history:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
    
    return {"ticket_id": ticket_id, "history": history}
