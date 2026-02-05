"""
Pytest configuration and fixtures for all tests.
"""
import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from motor.motor_asyncio import AsyncIOMotorClient
import os
from unittest.mock import AsyncMock, patch


@pytest.fixture(scope="session")
def event_loop():
    """
    Create an event loop for the entire test session.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
def reset_mongo_client():
    """
    Reset the global MongoDB client before each test to avoid event loop issues.
    """
    import src.db.mongo as mongo_module
    # Reset the global client so it gets recreated with the correct event loop
    mongo_module._client = None
    yield
    # Clean up after test
    if mongo_module._client:
        mongo_module._client.close()
        mongo_module._client = None


@pytest_asyncio.fixture(scope="function", autouse=False)
async def client():
    """
    Async HTTP client for testing FastAPI endpoints.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="function", autouse=False)
async def db():
    """
    MongoDB database connection for tests.
    Returns the database instance that works with the current event loop.
    """
    from src.db.mongo import get_db
    database = await get_db()
    yield database


@pytest_asyncio.fixture(scope="function", autouse=True)
async def ensure_indexes():
    """
    Ensure all indexes are created before each test.
    CRITICAL: This prevents race conditions where distributed lock tests
    run before the unique index on distributed_locks.resource_id is created.
    Without this, the atomic insert in acquire_lock() won't work correctly.
    """
    from src.db.indexes import create_indexes
    await create_indexes()
    yield


@pytest.fixture(scope="function", autouse=True)
def isolate_tests():
    """
    Ensure test isolation by resetting any global state between tests.
    """
    # Reset any global circuit breakers, rate limiters, etc.
    from src.services import circuit_breaker, rate_limiter
    
    # Clear circuit breaker instances
    if hasattr(circuit_breaker, '_instances'):
        circuit_breaker._instances = {}
    
    # Clear rate limiter state
    if hasattr(rate_limiter, '_buckets'):
        rate_limiter._buckets = {}
    
    yield
    
    # Cleanup after test
    pass
