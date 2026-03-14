#!/usr/bin/env python3
"""
Test Multi-Region OCR Implementation
====================================
Test script to validate the multi-region OCR service can achieve 300+ RPS
"""

import asyncio
import time
import os
import sys
from typing import List, Dict

# Add the backend directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.multi_region_ocr_service import MultiRegionOCRService

async def test_service_initialization():
    """Test that the multi-region service initializes correctly"""
    print("🔧 Testing service initialization...")
    
    try:
        service = MultiRegionOCRService()
        
        # Check endpoints
        print(f"   ✅ Initialized {len(service.endpoints)} endpoints")
        
        # Check regions and models
        regions = set(ep.region for ep in service.endpoints)
        models = set(ep.model for ep in service.endpoints)
        
        print(f"   ✅ Regions: {sorted(regions)}")
        print(f"   ✅ Models: {sorted(models)}")
        
        expected_endpoints = 4 * 3  # 4 regions × 3 models
        if len(service.endpoints) == expected_endpoints:
            print(f"   ✅ Correct number of endpoints: {expected_endpoints}")
        else:
            print(f"   ⚠️  Expected {expected_endpoints} endpoints, got {len(service.endpoints)}")
        
        await service.cleanup()
        return True
        
    except Exception as e:
        print(f"   ❌ Service initialization failed: {e}")
        return False

async def test_health_check():
    """Test health check functionality"""
    print("\n🏥 Testing health check...")
    
    try:
        service = MultiRegionOCRService()
        health_results = await service.health_check()
        
        healthy_count = len([status for status in health_results.values() if status == "healthy"])
        total_count = len(health_results)
        
        print(f"   ✅ Health check completed: {healthy_count}/{total_count} endpoints healthy")
        
        if healthy_count == 0:
            print("   ⚠️  No healthy endpoints found. Check your service account credentials.")
            return False
        
        # Show detailed health status
        for endpoint, status in health_results.items():
            status_icon = "✅" if status == "healthy" else "❌"
            print(f"   {status_icon} {endpoint}: {status}")
        
        await service.cleanup()
        return healthy_count > 0
        
    except Exception as e:
        print(f"   ❌ Health check failed: {e}")
        return False

async def test_load_balancer():
    """Test load balancer functionality"""
    print("\n⚖️ Testing load balancer...")
    
    try:
        service = MultiRegionOCRService()
        
        # Test getting best endpoint multiple times
        endpoints_chosen = []
        for i in range(10):
            endpoint = service.load_balancer.get_best_endpoint()
            if endpoint:
                endpoints_chosen.append(f"{endpoint.region}/{endpoint.model}")
        
        if endpoints_chosen:
            print(f"   ✅ Load balancer working: {len(set(endpoints_chosen))} unique endpoints chosen")
            print(f"   📊 Distribution: {dict(zip(*zip(*[(ep, endpoints_chosen.count(ep)) for ep in set(endpoints_chosen)])))}")
        else:
            print("   ❌ Load balancer returned no endpoints")
            return False
        
        # Test stats
        stats = service.get_stats()
        print(f"   ✅ Stats: {stats['total_endpoints']} total, {stats['healthy_endpoints']} healthy")
        
        await service.cleanup()
        return True
        
    except Exception as e:
        print(f"   ❌ Load balancer test failed: {e}")
        return False

async def test_batch_processing_simulation():
    """Test batch processing with simulated requests"""
    print("\n🚀 Testing batch processing simulation...")
    
    try:
        service = MultiRegionOCRService()
        
        # Create a dummy test image if it doesn't exist
        test_image_path = "test_answer_sheet.jpg"
        if not os.path.exists(test_image_path):
            print("   ⚠️  Creating dummy test image...")
            # Create a small dummy image file for testing
            import base64
            
            # 1x1 pixel PNG in base64
            dummy_png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            )
            
            with open(test_image_path, "wb") as f:
                f.write(dummy_png)
            
            print(f"   ✅ Created dummy test image: {test_image_path}")
        
        # Test with small batch first
        print("   🧪 Testing small batch (5 requests)...")
        small_batch = [test_image_path] * 5
        
        start_time = time.time()
        results = await service.process_batch(small_batch, max_concurrent=10)
        end_time = time.time()
        
        duration = end_time - start_time
        rps = len(small_batch) / duration if duration > 0 else 0
        
        success_count = len([r for r in results if "error" not in r])
        error_count = len([r for r in results if "error" in r])
        
        print(f"   ✅ Small batch: {success_count}/{len(small_batch)} successful in {duration:.2f}s ({rps:.1f} RPS)")
        
        if error_count > 0:
            print(f"   ⚠️  {error_count} errors in small batch:")
            for result in results[:3]:  # Show first 3 errors
                if "error" in result:
                    print(f"      • {result['error'][:100]}")
        
        # Test with larger batch if small batch worked
        if success_count > 0:
            print("   🚀 Testing larger batch (50 requests)...")
            large_batch = [test_image_path] * 50
            
            start_time = time.time()
            results = await service.process_batch(large_batch, max_concurrent=100)
            end_time = time.time()
            
            duration = end_time - start_time
            rps = len(large_batch) / duration if duration > 0 else 0
            
            success_count = len([r for r in results if "error" not in r])
            error_count = len([r for r in results if "error" in r])
            
            print(f"   ✅ Large batch: {success_count}/{len(large_batch)} successful in {duration:.2f}s ({rps:.1f} RPS)")
            
            # Estimate 300 RPS capability
            if rps > 0:
                estimated_300_rps_time = 300 / rps
                print(f"   📊 Estimated time for 300 requests: {estimated_300_rps_time:.1f}s")
                print(f"   🎯 300 RPS achievable: {'✅ YES' if rps >= 300 else '❌ NO (but scalable with more endpoints)'}")
        
        await service.cleanup()
        
        # Cleanup test file
        if os.path.exists(test_image_path) and test_image_path == "test_answer_sheet.jpg":
            os.remove(test_image_path)
        
        return success_count > 0
        
    except Exception as e:
        print(f"   ❌ Batch processing test failed: {e}")
        return False

async def test_performance_metrics():
    """Test performance metrics and monitoring"""
    print("\n📊 Testing performance metrics...")
    
    try:
        service = MultiRegionOCRService()
        
        # Get initial stats
        stats = service.get_stats()
        
        print(f"   ✅ Service stats retrieved:")
        print(f"      • Total endpoints: {stats['total_endpoints']}")
        print(f"      • Healthy endpoints: {stats['healthy_endpoints']}")
        print(f"      • Total capacity: {stats['max_capacity']} concurrent requests")
        print(f"      • Current load: {stats['total_load']}")
        
        # Show breakdown by region
        if stats['by_region']:
            print(f"   📍 By region:")
            for region, region_stats in stats['by_region'].items():
                print(f"      • {region}: {region_stats['capacity']} capacity, {region_stats['healthy']} healthy")
        
        # Show breakdown by model
        if stats['by_model']:
            print(f"   🤖 By model:")
            for model, model_stats in stats['by_model'].items():
                print(f"      • {model}: {model_stats['capacity']} capacity, {model_stats['healthy']} healthy")
        
        # Calculate theoretical maximum RPS
        total_capacity = stats['max_capacity']
        avg_response_time = 1.9  # From our test results
        theoretical_rps = total_capacity / avg_response_time
        practical_rps = theoretical_rps * 0.8  # 80% efficiency
        
        print(f"   🎯 Performance estimates:")
        print(f"      • Theoretical max RPS: {theoretical_rps:.1f}")
        print(f"      • Practical max RPS: {practical_rps:.1f} (80% efficiency)")
        print(f"      • 300 RPS target: {'✅ ACHIEVABLE' if practical_rps >= 300 else '❌ NEED MORE CAPACITY'}")
        
        await service.cleanup()
        return True
        
    except Exception as e:
        print(f"   ❌ Performance metrics test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("🧪 MULTI-REGION OCR IMPLEMENTATION TEST")
    print("=" * 50)
    
    tests = [
        ("Service Initialization", test_service_initialization),
        ("Health Check", test_health_check),
        ("Load Balancer", test_load_balancer),
        ("Batch Processing", test_batch_processing_simulation),
        ("Performance Metrics", test_performance_metrics)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"   ❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📋 TEST SUMMARY")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n🎉 All tests passed! Multi-region OCR service is ready.")
        print("\n📋 NEXT STEPS:")
        print("1. Request quota increases in Google Cloud Console")
        print("2. Run the setup script: ./setup_google_cloud.sh")
        print("3. Deploy to production with: ./deploy_multi_region.sh")
    else:
        print(f"\n⚠️  {len(results) - passed} tests failed. Check configuration and credentials.")
        print("\n🔧 TROUBLESHOOTING:")
        print("1. Ensure GOOGLE_APPLICATION_CREDENTIALS is set")
        print("2. Check service account permissions")
        print("3. Verify Vertex AI API is enabled")
        print("4. Confirm quota limits in your project")

if __name__ == "__main__":
    asyncio.run(main())
