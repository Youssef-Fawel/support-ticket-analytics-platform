# Architecture & Design Decisions

## System Overview

This is a production-ready multi-tenant SaaS support ticket management system built with FastAPI, MongoDB, and modern async Python patterns.

```
┌─────────────┐
│   FastAPI   │ ◄─── HTTP Requests
│  (Router)   │
└──────┬──────┘
       │
       ├──► IngestService ──┬──► External API (paginated)
       │                    ├──► ClassifyService
       │                    ├──► NotifyService (with retry)
       │                    ├──► SyncService (change detection)
       │                    ├──► RateLimiter (global)
       │                    └──► LockService (atomic)
       │
       ├──► AnalyticsService ──► MongoDB (aggregation)
       │
       └──► MongoDB ◄──────────── Optimized Indexes
                  └──────────► Connection Pool
```

---

## Core Design Principles

### 1. **Database-Centric Processing**
**Why:** Minimize data transfer, maximize performance

- All analytics computed in MongoDB using aggregation pipelines
- Zero Python-side processing for stats
- Single round-trip for complex queries using `$facet`

**Example:**
```python
# Bad: Load all tickets into Python
tickets = await db.tickets.find({}).to_list()
stats = compute_stats_in_python(tickets)  # ❌

# Good: Let MongoDB do the work
stats = await db.tickets.aggregate(pipeline).to_list()  # ✅
```

### 2. **Atomic Operations for Consistency**
**Why:** Prevent race conditions in distributed environment

- Lock acquisition: `findOneAndUpdate` with upsert
- Prevents check-then-act races
- No external coordination needed

**Example:**
```python
# Bad: Check then act (race condition)
if not await db.locks.find_one({"resource_id": id}):  # ❌
    await db.locks.insert_one({"resource_id": id})

# Good: Atomic operation
result = await db.locks.find_one_and_update(  # ✅
    {"resource_id": id, "expires_at": {"$lt": now}},
    {"$set": {"resource_id": id, "expires_at": expires}},
    upsert=True
)
```

### 3. **Connection Pooling**
**Why:** Efficient resource usage, stable performance

- Single Motor client instance (singleton pattern)
- Configurable pool size (min=10, max=50)
- Automatic connection management

**Benefits:**
- No connection creation overhead per request
- Prevents connection exhaustion
- Graceful degradation under load

### 4. **Non-Blocking Async Operations**
**Why:** Don't block main request flow

- Notifications run in background tasks
- Failures logged, not raised
- Main ingestion continues regardless

**Example:**
```python
# Fire and forget notification
asyncio.create_task(self._send_with_retry(payload))
# Main flow continues immediately
```

---

## Key Architectural Patterns

### 1. Circuit Breaker Pattern (Task 11)

**Purpose:** Prevent cascading failures

```
CLOSED ──5 failures in 10 calls──► OPEN
  ▲                                  │
  │                                  │ 30 seconds
  │                                  ▼
  └──1 success── HALF_OPEN ◄──timing
                    │
                    └──1 failure──► OPEN
```

**Benefits:**
- Fast failure when service is down
- Automatic recovery attempts
- System remains responsive

### 2. Token Bucket / Sliding Window Rate Limiting (Task 10)

**Purpose:** Respect external API limits (60 req/min)

**Implementation:**
- Global rate limiter (shared across tenants)
- Thread-safe with `asyncio.Lock`
- Automatic waiting when limit reached

**Alternatives Provided:**
- Sliding Window: Tracks exact request times
- Token Bucket: Token refill over time

### 3. Distributed Locking (Task 8)

**Purpose:** Prevent concurrent ingestion for same tenant

**Implementation:**
- MongoDB-based atomic locks
- TTL-based expiration (60s)
- Lock refresh for long jobs

**Key Features:**
- No external dependencies (Redis, etc.)
- Zombie lock prevention (auto-expire)
- Owner verification for release

### 4. Soft Delete Pattern (Task 12)

**Purpose:** Maintain data history, support undelete

**Implementation:**
- `deleted_at` timestamp field
- All queries filter: `deleted_at: {$exists: false}`
- History tracking for audits

**Benefits:**
- Recoverable deletes
- Full audit trail
- No data loss

---

## Database Schema Design

### Collections

#### `tickets`
```javascript
{
  _id: ObjectId,
  external_id: String,       // From external API
  tenant_id: String,         // Multi-tenancy key
  customer_id: String,
  source: String,
  subject: String,
  message: String,
  status: String,
  urgency: String,           // Computed
  sentiment: String,         // Computed
  requires_action: Boolean,  // Computed
  created_at: Date,
  updated_at: Date,          // For change detection
  deleted_at: Date,          // Soft delete (optional)
}
```

**Indexes:**
- `{tenant_id: 1, external_id: 1}` - UNIQUE (idempotency)
- `{tenant_id: 1, created_at: -1}` - Temporal queries
- `{tenant_id: 1, status: 1, created_at: -1}` - Filtered queries
- `{tenant_id: 1, urgency: 1, created_at: -1}` - Urgent tickets
- `{tenant_id: 1, deleted_at: 1}` - Soft delete filtering
- `{tenant_id: 1, deleted_at: 1, created_at: -1, status: 1, urgency: 1}` - Stats optimized

#### `ingestion_jobs`
```javascript
{
  _id: ObjectId,
  job_id: String,           // UUID
  tenant_id: String,
  status: String,           // running, completed, cancelled, failed
  started_at: Date,
  ended_at: Date,
  progress: Number,         // 0-100
  total_pages: Number,
  processed_pages: Number
}
```

#### `ingestion_logs`
```javascript
{
  _id: ObjectId,
  tenant_id: String,
  job_id: String,
  status: String,
  started_at: Date,
  ended_at: Date,
  new_ingested: Number,
  updated: Number,
  errors: Number,
  error: String            // If failed
}
```

#### `distributed_locks`
```javascript
{
  _id: ObjectId,
  resource_id: String,     // UNIQUE
  owner_id: String,        // Job ID
  acquired_at: Date,
  expires_at: Date         // TTL = acquired_at + 60s
}
```

#### `ticket_history`
```javascript
{
  _id: ObjectId,
  ticket_id: String,
  tenant_id: String,
  action: String,          // created, updated, deleted
  changes: Object,         // {field: {old: x, new: y}}
  recorded_at: Date
}
```

---

## Service Layer Architecture

### IngestService
**Responsibilities:**
- Coordinate ingestion workflow
- Handle pagination manually
- Manage job state
- Integrate all sub-services

**Key Methods:**
- `run_ingestion()` - Main orchestration
- `_fetch_page_with_retry()` - Handle 429
- `get_job_status()` - Progress tracking
- `cancel_job()` - Graceful cancellation

### ClassifyService
**Responsibilities:**
- Rule-based ticket classification
- Keyword matching
- Urgency/sentiment/action detection

**Design:**
- Stateless (static methods)
- No external dependencies
- Easily extensible keyword lists

### NotifyService
**Responsibilities:**
- Send notifications to external API
- Manual retry with exponential backoff
- Circuit breaker integration

**Key Features:**
- Non-blocking (fire-and-forget)
- Configurable retry attempts
- Jitter to prevent thundering herd

### LockService
**Responsibilities:**
- Distributed lock management
- Atomic operations
- TTL-based expiration

**Key Methods:**
- `acquire_lock()` - Atomic acquisition
- `release_lock()` - Owner verification
- `refresh_lock()` - Extend TTL
- `get_lock_status()` - Inspection

### RateLimiter
**Responsibilities:**
- Global rate limiting
- Thread-safe operations
- Configurable limits

**Implementations:**
- Sliding Window: Precise request tracking
- Token Bucket: Smoother distribution

### CircuitBreaker
**Responsibilities:**
- Failure detection
- Automatic recovery
- State management

**States:**
- CLOSED: Normal operation
- OPEN: Fail fast
- HALF_OPEN: Testing recovery

### SyncService
**Responsibilities:**
- Change detection
- Soft delete handling
- History tracking

**Key Methods:**
- `sync_ticket()` - Compare and update
- `mark_deleted()` - Soft delete
- `detect_deleted_tickets()` - Find missing
- `record_history()` - Audit trail

### AnalyticsService
**Responsibilities:**
- Database-only aggregations
- High-performance queries
- Complex metrics computation

**Key Features:**
- Single `$facet` pipeline
- No Python processing
- Optimized for 10k+ documents

---

## Performance Optimizations

### 1. Index Strategy

**Compound Index Design:**
```
{tenant_id: 1, created_at: -1}
```

**Why tenant_id first?**
- Every query filters by tenant
- High selectivity (tenant count)
- Enables index-only queries

**Stats-Optimized Index:**
```
{tenant_id: 1, deleted_at: 1, created_at: -1, status: 1, urgency: 1}
```

**Why this order?**
- Filter by tenant (highest selectivity)
- Filter out deletes (moderate selectivity)
- Sort by created_at (most common)
- Group by status/urgency (low selectivity)

### 2. Aggregation Pipeline

**Use `$facet` for parallel processing:**
```python
{
  "$facet": {
    "total": [...],
    "by_status": [...],
    "urgency_stats": [...],
    "hourly_trend": [...],
    "keywords": [...],
    "at_risk": [...]
  }
}
```

**Benefits:**
- Single database round-trip
- Parallel execution
- Reduced network overhead

### 3. Connection Pooling

**Configuration:**
```python
maxPoolSize=50       # Max concurrent connections
minPoolSize=10       # Always ready connections
maxIdleTimeMS=45000  # Close idle after 45s
```

**Trade-offs:**
- Higher min = faster response, more memory
- Lower max = safer, may queue under load

---

## Error Handling Strategy

### 1. Graceful Degradation
- Notification failures don't block ingestion
- Circuit breaker prevents cascading failures
- Partial ingestion success recorded

### 2. Comprehensive Logging
- Every ingestion logged (success or failure)
- Error context preserved
- Traceability via job_id

### 3. Idempotency
- Re-running ingestion safe
- Duplicate detection via unique index
- Upsert operations only

---

## Security Considerations

### 1. Multi-Tenant Isolation
- Every query includes `tenant_id`
- No cross-tenant data access
- Enforced at data layer

### 2. Input Validation
- Pydantic models for request validation
- Type checking
- Range validation (page size, etc.)

### 3. Resource Limits
- Rate limiting prevents abuse
- Lock expiration prevents deadlocks
- Connection pooling prevents exhaustion

---

## Scalability Considerations

### Horizontal Scaling
**Can Scale:**
- API servers (stateless)
- Background workers (with distributed locks)

**Cannot Scale (yet):**
- Rate limiter (in-memory, global)
- Circuit breaker (per-instance state)

**Solutions for Future:**
- Move rate limiter to Redis
- Shared circuit breaker state
- Distributed job queue

### Vertical Scaling
**Current Limits:**
- MongoDB connection pool (50)
- Rate limit (60 req/min)
- Lock TTL (60s)

**Tuning Parameters:**
- Increase pool size for more concurrency
- Adjust rate limit per external API
- Longer TTL for slower ingestion

---

## Testing Strategy

### 1. Unit Tests
- Service layer methods
- Classification logic
- Lock operations

### 2. Integration Tests
- Full ingestion workflow
- Database operations
- External API mocking

### 3. Performance Tests
- Stats query with 10k+ tickets
- Concurrent ingestion
- Rate limiter under load

### 4. Edge Cases
- Race conditions (concurrent ingestion)
- Memory leaks (cache cleanup)
- Multi-tenant isolation
- Slow queries (index optimization)

---

## Monitoring & Observability

### Health Check
- MongoDB connectivity
- External API availability
- Non-200 on failure

### Metrics to Track
- Ingestion success/failure rate
- Stats query latency
- Circuit breaker state changes
- Lock contention
- Rate limiter saturation

### Audit Trail
- ingestion_logs: Every run
- ticket_history: Every change
- Job progress: Real-time updates

---

## Trade-offs & Decisions

### 1. In-Memory vs. Distributed State

**Decision:** In-memory for rate limiter and circuit breaker

**Trade-off:**
- ✅ Simpler implementation
- ✅ Lower latency
- ❌ Not shared across instances
- ❌ Lost on restart

**Rationale:** Acceptable for this scale; can migrate to Redis if needed

### 2. Manual Retry vs. Library

**Decision:** Manual implementation with asyncio

**Trade-off:**
- ✅ Meets requirements
- ✅ No external dependencies
- ✅ Full control
- ❌ More code to maintain

**Rationale:** Requirement constraint

### 3. MongoDB vs. Relational

**Decision:** MongoDB (given)

**Trade-off:**
- ✅ Flexible schema
- ✅ Powerful aggregation
- ✅ Horizontal scaling
- ❌ No ACID across collections
- ❌ Eventual consistency

**Rationale:** Good fit for document-based data

---

## Future Enhancements

### Short Term
1. Add Redis for distributed state
2. Implement metrics collection (Prometheus)
3. Add request ID tracing
4. Implement retry queue for failed notifications

### Medium Term
1. Add GraphQL API
2. Implement full-text search (Elasticsearch)
3. Add real-time updates (WebSockets)
4. Implement batch ingestion

### Long Term
1. Machine learning for classification
2. Predictive analytics
3. Auto-scaling based on load
4. Multi-region deployment

---

## Conclusion

This architecture provides a **production-ready** foundation with:
- ✅ High performance (database-centric)
- ✅ Reliability (retries, circuit breakers)
- ✅ Scalability (connection pooling, indexes)
- ✅ Maintainability (clean separation of concerns)
- ✅ Observability (health checks, audit logs)
- ✅ Security (tenant isolation)

All design decisions align with the **critical constraints** while following **best practices** for async Python and MongoDB.
