from src.db.mongo import get_db
import pymongo


async def create_indexes():
    """
    Create MongoDB indexes required for common query patterns and to keep
    the dataset manageable over time (e.g. compound indexes, unique
    constraints, TTL on old data).
    
    ✅ DEBUG TASK E FIXED: Optimized indexes for performance
    Target: <500ms for stats query with 10k+ tickets
    """
    db = await get_db()
    tickets = db.tickets

    # ============================================================
    # ✅ OPTIMIZED INDEXES FOR HIGH PERFORMANCE
    # ============================================================

    # 1. Unique index for idempotency (prevents duplicate tickets)
    await tickets.create_index(
        [("tenant_id", pymongo.ASCENDING), ("external_id", pymongo.ASCENDING)],
        unique=True,
        name="unique_tenant_external_id"
    )

    # 2. Efficient composite index (tenant_id first, then created_at)
    # Supports: tenant queries with time-based sorting
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("created_at", pymongo.DESCENDING)
        ],
        name="tenant_created_at"
    )

    # 3. Composite index for filtered queries
    # Supports: queries filtering by tenant, status, and sorting by date
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("status", pymongo.ASCENDING),
            ("created_at", pymongo.DESCENDING)
        ],
        name="tenant_status_created"
    )

    # 4. TTL index for automatic data cleanup (30 days)
    # Note: This is optional - remove if you want to keep data indefinitely
    await tickets.create_index(
        [("created_at", pymongo.ASCENDING)],
        expireAfterSeconds=2592000,  # 30 days in seconds
        name="ttl_created_at"
    )

    # 5. Index for urgency queries
    # Supports: finding high-urgency tickets per tenant
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("urgency", pymongo.ASCENDING),
            ("created_at", pymongo.DESCENDING)
        ],
        name="tenant_urgency_created"
    )

    # 5. Index for sentiment analysis
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("sentiment", pymongo.ASCENDING)
        ],
        name="tenant_sentiment"
    )

    # 6. Index for source filtering
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("source", pymongo.ASCENDING)
        ],
        name="tenant_source"
    )

    # 7. Index for soft-delete filtering (Task 12)
    # Critical for excluding deleted tickets efficiently
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("deleted_at", pymongo.ASCENDING)
        ],
        name="tenant_deleted_at"
    )

    # 8. Index for customer-based queries
    # Supports: finding all tickets for a customer (at-risk analysis)
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("customer_id", pymongo.ASCENDING)
        ],
        name="tenant_customer"
    )

    # 9. Index for updated_at (Task 12 - change detection)
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("updated_at", pymongo.ASCENDING)
        ],
        name="tenant_updated_at"
    )

    # 10. Compound index optimized for stats aggregation
    # Supports the faceted aggregation in analytics service
    await tickets.create_index(
        [
            ("tenant_id", pymongo.ASCENDING),
            ("deleted_at", pymongo.ASCENDING),
            ("created_at", pymongo.DESCENDING),
            ("status", pymongo.ASCENDING),
            ("urgency", pymongo.ASCENDING)
        ],
        name="stats_optimized"
    )

    # ingestion_jobs collection indexes
    ingestion_jobs = db.ingestion_jobs
    await ingestion_jobs.create_index(
        [("tenant_id", pymongo.ASCENDING), ("status", pymongo.ASCENDING)],
        name="tenant_status"
    )
    await ingestion_jobs.create_index(
        [("job_id", pymongo.ASCENDING)],
        unique=True,
        sparse=True,
        name="job_id_unique"
    )
    await ingestion_jobs.create_index(
        [("started_at", pymongo.DESCENDING)],
        name="started_at"
    )

    # ingestion_logs collection indexes
    ingestion_logs = db.ingestion_logs
    await ingestion_logs.create_index(
        [("tenant_id", pymongo.ASCENDING), ("started_at", pymongo.DESCENDING)],
        name="tenant_started"
    )
    await ingestion_logs.create_index(
        [("job_id", pymongo.ASCENDING)],
        name="job_id"
    )

    # distributed_locks collection indexes (Task 8)
    distributed_locks = db.distributed_locks
    await distributed_locks.create_index(
        [("resource_id", pymongo.ASCENDING)],
        unique=True,
        name="resource_id_unique"
    )
    await distributed_locks.create_index(
        [("expires_at", pymongo.ASCENDING)],
        name="expires_at"
    )

    # ticket_history collection indexes (Task 12)
    ticket_history = db.ticket_history
    await ticket_history.create_index(
        [("ticket_id", pymongo.ASCENDING), ("recorded_at", pymongo.DESCENDING)],
        name="ticket_recorded"
    )
    await ticket_history.create_index(
        [("tenant_id", pymongo.ASCENDING), ("recorded_at", pymongo.DESCENDING)],
        name="tenant_recorded"
    )
