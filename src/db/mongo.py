from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os
import asyncio

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = "support_saas"

# Global client instance (singleton pattern for connection pooling)
_client: Optional[AsyncIOMotorClient] = None
_client_event_loop: Optional[asyncio.AbstractEventLoop] = None

def get_client() -> AsyncIOMotorClient:
    """
    Get or create a MongoDB client instance.
    Uses a singleton pattern to maintain a single connection pool.
    
    Task 7: Proper resource management and stability.
    The Motor driver handles connection pooling automatically.
    
    If the event loop has changed (e.g., in tests), recreate the client.
    """
    global _client, _client_event_loop
    
    try:
        current_loop = asyncio.get_event_loop()
    except RuntimeError:
        current_loop = None
    
    # Recreate client if it doesn't exist or if the event loop has changed
    if _client is None or _client_event_loop != current_loop:
        if _client is not None:
            _client.close()
        
        _client = AsyncIOMotorClient(
            MONGO_URL,
            maxPoolSize=50,  # Maximum connections in pool
            minPoolSize=10,  # Minimum connections to maintain
            maxIdleTimeMS=45000,  # Close idle connections after 45s
            serverSelectionTimeoutMS=5000,  # Timeout for server selection
            connectTimeoutMS=10000,  # Timeout for initial connection
            socketTimeoutMS=45000,  # Timeout for socket operations
        )
        _client_event_loop = current_loop
    
    return _client

async def get_db():
    """
    Returns a database instance.
    
    Reuses the same client connection pool for optimal performance.
    """
    client = get_client()
    return client[DB_NAME]

async def close_db():
    """
    Close the MongoDB connection.
    Should be called on application shutdown.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None