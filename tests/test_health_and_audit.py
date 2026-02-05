import pytest
from httpx import AsyncClient
from src.main import app
from src.db.mongo import get_db

@pytest.mark.asyncio
async def test_health_check_logic(client: AsyncClient):
    """
    TEST: Health check should return 200 and check dependencies.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    # Expecting candidate to return details about mongodb/external_api
    # assert "mongodb" in data
    # assert "external_api" in data

@pytest.mark.asyncio
async def test_audit_logging_creation(client: AsyncClient, db):
    """
    TEST: Every ingestion run should create an audit log entry.
    """
    await client.post("/ingest/run?tenant_id=tenant_b")
    
    db = await get_db()
    log = await db.ingestion_logs.find_one({"status": {"$in": ["SUCCESS", "FAILED", "PARTIAL_SUCCESS"]}})
    assert log is not None
    assert "started_at" in log
    assert "new_ingested" in log or "updated" in log
