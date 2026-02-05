# Quick Testing Guide

## Prerequisites
Ensure Docker and Docker Compose are installed.

## Starting the System

```bash
# Start all services
docker-compose up --build

# The system will be available at:
# - API: http://localhost:8000
# - Mock External API: http://localhost:9000
```

## Manual Testing Commands

### 1. Health Check
```bash
curl http://localhost:8000/health
```
Expected: 200 OK with MongoDB and external API status

### 2. Run Ingestion
```bash
# Start ingestion for tenant1
curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant1"

# Response includes job_id for tracking
```

### 3. Check Ingestion Status
```bash
# Get current status for tenant
curl "http://localhost:8000/ingest/status?tenant_id=tenant1"
```

### 4. Get Ingestion Progress
```bash
# Replace {job_id} with actual job_id from ingestion response
curl "http://localhost:8000/ingest/progress/{job_id}"
```

### 5. List Tickets
```bash
# Get tickets for tenant1
curl "http://localhost:8000/tickets?tenant_id=tenant1&page=1&page_size=20"

# Filter by status
curl "http://localhost:8000/tickets?tenant_id=tenant1&status=open"

# Filter by urgency
curl "http://localhost:8000/tickets?tenant_id=tenant1&urgency=high"
```

### 6. Get Analytics
```bash
# Get stats for tenant1
curl "http://localhost:8000/tenants/tenant1/stats"

# Expected: total_tickets, by_status, urgency_high_ratio, hourly_trend, etc.
```

### 7. Get Urgent Tickets
```bash
curl "http://localhost:8000/tickets/urgent?tenant_id=tenant1"
```

### 8. Circuit Breaker Status
```bash
# Check notify circuit breaker status
curl "http://localhost:8000/circuit/notify/status"

# Reset circuit breaker (for testing)
curl -X POST "http://localhost:8000/circuit/notify/reset"
```

### 9. Lock Status
```bash
# Check lock status for tenant
curl "http://localhost:8000/ingest/lock/tenant1"
```

### 10. Cancel Ingestion
```bash
# Cancel a running ingestion job
curl -X DELETE "http://localhost:8000/ingest/{job_id}"
```

### 11. Ticket History
```bash
# Get change history for a ticket
curl "http://localhost:8000/tickets/{ticket_id}/history?tenant_id=tenant1"
```

## Running Automated Tests

```bash
# Run all tests
docker-compose exec app pytest

# Run specific test file
docker-compose exec app pytest tests/test_basic_endpoints.py

# Run with verbose output
docker-compose exec app pytest -v

# Run with coverage
docker-compose exec app pytest --cov=src
```

## Testing Concurrent Ingestion (Task 8)

```bash
# In terminal 1:
curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant1"

# Quickly in terminal 2 (should get 409 Conflict):
curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant1"
```

## Testing Rate Limiting (Task 10)

```bash
# Rapid fire requests to trigger rate limiting
for i in {1..70}; do
  curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant$i" &
done
wait

# Check logs for rate limiting messages
docker-compose logs app | grep "Rate limited"
```

## Testing Multi-tenant Isolation (Debug Task A)

```bash
# Ingest for tenant1
curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant1"

# Ingest for tenant2
curl -X POST "http://localhost:8000/ingest/run?tenant_id=tenant2"

# Verify tenant1 only sees their tickets
curl "http://localhost:8000/tickets?tenant_id=tenant1"

# Verify tenant2 only sees their tickets
curl "http://localhost:8000/tickets?tenant_id=tenant2"

# Confirm no cross-tenant data leakage
```

## Testing Stats Performance (Debug Task E)

```bash
# After ingesting 10,000+ tickets
curl "http://localhost:8000/tenants/tenant1/stats"

# Response should be < 500ms
# Check response time in headers or use:
time curl "http://localhost:8000/tenants/tenant1/stats"
```

## Monitoring Logs

```bash
# Follow all logs
docker-compose logs -f

# Follow just the app logs
docker-compose logs -f app

# Search for specific events
docker-compose logs app | grep "ERROR"
docker-compose logs app | grep "notification"
docker-compose logs app | grep "Circuit"
```

## Database Inspection

```bash
# Connect to MongoDB
docker-compose exec mongodb mongosh

# In MongoDB shell:
use support_saas

# Check collections
show collections

# Count tickets
db.tickets.countDocuments()

# Check ingestion logs
db.ingestion_logs.find().sort({started_at: -1}).limit(5)

# Check indexes
db.tickets.getIndexes()

# Check for duplicates (should be 0)
db.tickets.aggregate([
  {$group: {_id: {tenant_id: "$tenant_id", external_id: "$external_id"}, count: {$sum: 1}}},
  {$match: {count: {$gt: 1}}}
])
```

## Performance Testing

```bash
# Install Apache Bench (ab) if needed
# apt-get install apache2-utils

# Test stats endpoint performance
ab -n 100 -c 10 "http://localhost:8000/tenants/tenant1/stats"

# Test ticket listing
ab -n 100 -c 10 "http://localhost:8000/tickets?tenant_id=tenant1"
```

## Clean Up

```bash
# Stop all services
docker-compose down

# Remove volumes (clean database)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## Common Issues

### Port Already in Use
```bash
# Check what's using port 8000
lsof -i :8000  # Linux/Mac
netstat -ano | findstr :8000  # Windows

# Kill the process or change port in docker-compose.yml
```

### MongoDB Connection Issues
```bash
# Check if MongoDB is running
docker-compose ps

# Restart MongoDB
docker-compose restart mongodb

# Check logs
docker-compose logs mongodb
```

### Tests Failing
```bash
# Ensure fresh start
docker-compose down -v
docker-compose up --build

# Wait for services to be ready
sleep 10

# Run tests
docker-compose exec app pytest
```

## Expected Test Results

All tests should pass:
- ✅ test_analytics_aggregation.py
- ✅ test_basic_endpoints.py
- ✅ test_circuit_breaker.py
- ✅ test_concurrent_ingestion.py
- ✅ test_data_sync.py
- ✅ test_debug_tasks.py
- ✅ test_dedup_and_indexes.py
- ✅ test_health_and_audit.py
- ✅ test_hidden_edge_cases.py
- ✅ test_notification_retry.py
- ✅ test_rate_limiting.py

## Success Indicators

1. **Health Check:** Returns 200 with all dependencies healthy
2. **Ingestion:** Completes successfully with job_id returned
3. **Stats Query:** Returns in <500ms with meaningful data
4. **Concurrent Ingestion:** Second request returns 409 Conflict
5. **Multi-tenant:** No data leakage between tenants
6. **Rate Limiting:** 429 responses after 60 requests/minute
7. **Circuit Breaker:** Opens after 5 failures, closes after recovery
8. **Soft Delete:** Deleted tickets excluded from queries
9. **No Memory Leak:** Memory usage stable across multiple ingestions
10. **Audit Trail:** All ingestion runs logged in ingestion_logs
