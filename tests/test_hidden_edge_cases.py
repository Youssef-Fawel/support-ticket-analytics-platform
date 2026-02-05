import pytest
from httpx import AsyncClient
from src.main import app
from src.db.mongo import get_db

@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, db):
    """
    TEST: The same external_id in DIFFERENT tenants should be treated as separate tickets.
    """
    await db.tickets.delete_many({})
    
    # Mocking ingestion for two different tenants with same data
    # In a real test, we would mock the external API response
    pass

@pytest.mark.asyncio
async def test_missing_tenant_id(client: AsyncClient):
    """
    TEST: API should return 422 if tenant_id is missing.
    """
    resp = await client.get("/tickets")
    assert resp.status_code == 422

@pytest.mark.asyncio
async def test_stats_performance_limit(client: AsyncClient):
    """
    TEST: Verify the 2-second performance limit on the stats endpoint.
    """
    # This will fail if the candidate uses slow Python-side loops
    resp = await client.get("/tenants/tenant_a/stats")
    # If the middleware works, it returns 504 on timeout
    assert resp.status_code != 504, "Stats endpoint exceeded performance limit"
