#!/usr/bin/env python3
"""
Quick test script to verify API is running correctly.

Usage:
    poetry run python test_api.py
"""

import httpx

BASE_URL = "http://localhost:8000"


def test_endpoints():
    """Test all health endpoints."""
    
    print("🧪 Testing Enterprise AI Platform API...")
    print(f"Base URL: {BASE_URL}\n")
    
    with httpx.Client() as client:
        # Test root endpoint
        print("1️⃣ Testing root endpoint (/)...")
        try:
            response = client.get(f"{BASE_URL}/")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.json()}")
            print(f"   ✅ Root endpoint working!\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")
        
        # Test health endpoint
        print("2️⃣ Testing health endpoint (/health)...")
        try:
            response = client.get(f"{BASE_URL}/health")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.json()}")
            print(f"   ✅ Health endpoint working!\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")
        
        # Test liveness endpoint
        print("3️⃣ Testing liveness endpoint (/health/live)...")
        try:
            response = client.get(f"{BASE_URL}/health/live")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.json()}")
            print(f"   ✅ Liveness endpoint working!\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")
        
        # Test readiness endpoint
        print("4️⃣ Testing readiness endpoint (/health/ready)...")
        try:
            response = client.get(f"{BASE_URL}/health/ready")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.json()}")
            print(f"   ✅ Readiness endpoint working!\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")
        
        # Test with custom headers
        print("5️⃣ Testing with custom headers (trace_id, tenant_id)...")
        try:
            headers = {
                "X-Trace-ID": "test-trace-123",
                "X-Tenant-ID": "test-tenant",
            }
            response = client.get(f"{BASE_URL}/health", headers=headers)
            print(f"   Status: {response.status_code}")
            print(f"   Response Headers:")
            print(f"     X-Trace-ID: {response.headers.get('X-Trace-ID')}")
            print(f"     X-Tenant-ID: {response.headers.get('X-Tenant-ID')}")
            print(f"     X-Request-Duration-Ms: {response.headers.get('X-Request-Duration-Ms')}")
            print(f"   ✅ Custom headers working!\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")
    
    print("✅ All tests completed!")
    print(f"\n📚 View API docs at: {BASE_URL}/docs")
    print(f"📘 View ReDoc at: {BASE_URL}/redoc")


if __name__ == "__main__":
    test_endpoints()
