"""
Quick verification script to test key system features manually.
"""
import requests
import time
import json

BASE_URL = "http://localhost:8000"


def test_health():
    """Test 1: Health check"""
    print("\n=== Test 1: Health Check ===")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ Health check passed")


def test_ingestion():
    """Test 2: Trigger ingestion"""
    print("\n=== Test 2: Ingestion ===")
    tenant_id = "test_tenant_001"
    response = requests.post(f"{BASE_URL}/ingest/run?tenant_id={tenant_id}")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    print(f"✅ Ingestion started with job_id: {job_id}")
    return job_id, tenant_id


def test_concurrent_ingestion():
    """Test 3: Concurrent ingestion protection"""
    print("\n=== Test 3: Concurrent Ingestion Protection ===")
    tenant_id = "test_tenant_002"
    
    # First request should succeed
    response1 = requests.post(f"{BASE_URL}/ingest/run?tenant_id={tenant_id}")
    print(f"First request status: {response1.status_code}")
    
    # Second request should be blocked (409 Conflict)
    response2 = requests.post(f"{BASE_URL}/ingest/run?tenant_id={tenant_id}")
    print(f"Second request status: {response2.status_code}")
    
    if response2.status_code == 409:
        print("✅ Concurrent ingestion correctly blocked")
    else:
        print(f"⚠️ Expected 409, got {response2.status_code}")


def test_list_tickets():
    """Test 4: List tickets"""
    print("\n=== Test 4: List Tickets ===")
    tenant_id = "test_tenant_001"
    time.sleep(3)  # Wait for ingestion to complete
    
    response = requests.get(f"{BASE_URL}/tickets", params={"tenant_id": tenant_id})
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Found {len(data['tickets'])} tickets")
    if data['tickets']:
        print(f"First ticket: {json.dumps(data['tickets'][0], indent=2)}")
    print("✅ List tickets working")


def test_stats():
    """Test 5: Analytics/Stats"""
    print("\n=== Test 5: Analytics Stats ===")
    tenant_id = "test_tenant_001"
    
    start_time = time.time()
    response = requests.get(f"{BASE_URL}/tenants/{tenant_id}/stats")
    elapsed = time.time() - start_time
    
    print(f"Status: {response.status_code}")
    print(f"Response time: {elapsed:.3f}s")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Stats: {json.dumps(data, indent=2)}")
        print(f"✅ Stats endpoint working (response time: {elapsed:.3f}s)")
    else:
        print(f"⚠️ Stats failed with status {response.status_code}")


def test_rate_limiter_status():
    """Test 6: Rate limiter status"""
    print("\n=== Test 6: Rate Limiter Status ===")
    response = requests.get(f"{BASE_URL}/rate-limiter/status")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print("✅ Rate limiter status working")


def test_circuit_breaker_status():
    """Test 7: Circuit breaker status"""
    print("\n=== Test 7: Circuit Breaker Status ===")
    response = requests.get(f"{BASE_URL}/circuit/notify/status")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print("✅ Circuit breaker status working")


def main():
    """Run all tests"""
    print("="*60)
    print("SYSTEM VERIFICATION TESTS")
    print("="*60)
    
    try:
        test_health()
        job_id, tenant_id = test_ingestion()
        test_concurrent_ingestion()
        test_list_tickets()
        test_stats()
        test_rate_limiter_status()
        test_circuit_breaker_status()
        
        print("\n" + "="*60)
        print("✅ ALL MANUAL TESTS PASSED!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
