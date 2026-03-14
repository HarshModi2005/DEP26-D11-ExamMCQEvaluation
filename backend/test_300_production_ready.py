#!/usr/bin/env python3
"""
Production-Ready Test: 300 OCR Requests
=======================================
Tests the optimized OCR service with real answer sheet images
"""

import asyncio
import time
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.optimized_ocr_service import OptimizedOCRService

async def test_production_load():
    """Test with 300 requests using real images"""
    
    print("="*70)
    print("🚀 PRODUCTION-READY OCR TEST - 300 REQUESTS")
    print("="*70)
    print("Target: Complete in 4-5 minutes (60-75 RPS)")
    print("="*70)
    
    # Use real images from the repository
    base_images = [
        "/Users/harsh/Desktop/DEP/Screenshot 2026-02-08 at 6.53.08 PM.png",
        "/Users/harsh/Desktop/DEP/WhatsApp Image 2026-02-09 at 12.05.08 PM.jpeg",
        "/Users/harsh/Desktop/DEP/WhatsApp Image 2026-02-09 at 12.04.58 PM.jpeg",
        "/Users/harsh/Desktop/DEP/temp_2.jpeg",
    ]
    
    # Verify images exist
    available_images = [img for img in base_images if os.path.exists(img)]
    
    if not available_images:
        print("❌ ERROR: No test images found!")
        return
    
    print(f"\n📸 Found {len(available_images)} real answer sheet images:")
    for img in available_images:
        print(f"   • {os.path.basename(img)}")
    
    # Create 300 requests by repeating images
    image_paths = (available_images * 100)[:300]
    print(f"\n📋 Created {len(image_paths)} requests (repeating {len(available_images)} images)")
    
    # Initialize optimized service
    service = OptimizedOCRService()
    
    print(f"\n⚙️  Service Configuration:")
    print(f"   • Endpoints: {len(service.endpoints)}")
    print(f"   • Connection pool: {service.connection_pool_size} connections")
    print(f"   • Batch size: {service.optimal_batch_size}")
    print(f"   • Image optimization: {service.max_image_size} @ {service.jpeg_quality}% JPEG")
    
    # Run the test
    print(f"\n{'='*70}")
    print(f"🏁 STARTING TEST")
    print(f"{'='*70}\n")
    
    start_time = time.time()
    
    results = await service.process_batch_optimized(
        image_paths,
        target_time_minutes=5.0
    )
    
    end_time = time.time()
    total_time = end_time - start_time
    total_minutes = total_time / 60
    
    # Detailed analysis
    print(f"\n{'='*70}")
    print(f"📊 COMPREHENSIVE RESULTS")
    print(f"{'='*70}")
    
    # Time metrics
    print(f"\n⏱️  TIME METRICS:")
    print(f"   • Total time: {total_time:.1f}s ({total_minutes:.2f} minutes)")
    print(f"   • Target time: 5.0 minutes")
    
    if total_minutes <= 4.0:
        print(f"   ✅ EXCELLENT: Completed in under 4 minutes!")
    elif total_minutes <= 5.0:
        print(f"   ✅ GOOD: Completed within target time!")
    elif total_minutes <= 6.0:
        print(f"   ⚠️  ACCEPTABLE: Slightly over target")
    else:
        print(f"   ❌ SLOW: Significantly over target")
    
    # Success metrics
    fully_successful = len([r for r in results 
                           if "error" not in r 
                           and r.get("entry_number") not in ["unknown", None, ""]
                           and len(r.get("answers", {})) > 0])
    
    partial_success = len([r for r in results 
                          if "error" not in r 
                          and (r.get("entry_number") in ["unknown", None, ""] 
                               or len(r.get("answers", {})) == 0)])
    
    errors = len([r for r in results if "error" in r])
    
    print(f"\n✅ SUCCESS METRICS:")
    print(f"   • Fully successful: {fully_successful}/{len(results)} ({fully_successful/len(results)*100:.1f}%)")
    print(f"   • Partial success: {partial_success}/{len(results)} ({partial_success/len(results)*100:.1f}%)")
    print(f"   • Errors: {errors}/{len(results)} ({errors/len(results)*100:.1f}%)")
    print(f"   • Overall success: {(fully_successful + partial_success)/len(results)*100:.1f}%")
    
    # Performance metrics
    avg_rps = len(results) / total_time if total_time > 0 else 0
    print(f"\n⚡ PERFORMANCE METRICS:")
    print(f"   • Average RPS: {avg_rps:.1f} requests/second")
    print(f"   • Peak theoretical: {len(service.endpoints) * 100} req/min per endpoint")
    
    processing_times = [r.get('processing_time', 0) for r in results if 'processing_time' in r]
    if processing_times:
        avg_time = sum(processing_times) / len(processing_times)
        print(f"   • Avg processing time: {avg_time:.2f}s")
        print(f"   • Min processing time: {min(processing_times):.2f}s")
        print(f"   • Max processing time: {max(processing_times):.2f}s")
    
    # Sample successful results
    successful_results = [r for r in results 
                         if "error" not in r 
                         and r.get("entry_number") not in ["unknown", None, ""]]
    
    if successful_results:
        print(f"\n📝 SAMPLE SUCCESSFUL EXTRACTIONS:")
        for i, r in enumerate(successful_results[:5], 1):
            answers_count = len(r.get("answers", {}))
            print(f"   {i}. Entry: {r.get('entry_number')}, "
                  f"Name: {r.get('name')}, "
                  f"Answers: {answers_count} questions, "
                  f"Time: {r.get('processing_time', 0):.2f}s")
    
    # Error breakdown
    if errors > 0:
        error_types = {}
        for r in results:
            if "error" in r:
                error_str = str(r["error"])
                # Categorize errors
                if "429" in error_str or "rate limit" in error_str.lower():
                    category = "Rate Limit (429)"
                elif "timeout" in error_str.lower():
                    category = "Timeout"
                elif "parse" in error_str.lower():
                    category = "Parse Error"
                elif "404" in error_str:
                    category = "Not Found (404)"
                elif "401" in error_str or "403" in error_str:
                    category = "Auth Error"
                else:
                    category = error_str[:50]
                
                error_types[category] = error_types.get(category, 0) + 1
        
        print(f"\n❌ ERROR BREAKDOWN:")
        for error, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
            print(f"   • {error}: {count} ({count/errors*100:.1f}% of errors)")
    
    # Endpoint distribution
    endpoint_usage = {}
    endpoint_errors = {}
    
    for r in results:
        if "endpoint" in r:
            ep = r["endpoint"]
            endpoint_usage[ep] = endpoint_usage.get(ep, 0) + 1
            if "error" in r:
                endpoint_errors[ep] = endpoint_errors.get(ep, 0) + 1
    
    print(f"\n🌍 ENDPOINT DISTRIBUTION:")
    for ep in sorted(endpoint_usage.keys()):
        count = endpoint_usage[ep]
        err_count = endpoint_errors.get(ep, 0)
        success_rate = ((count - err_count) / count * 100) if count > 0 else 0
        print(f"   • {ep}: {count} requests ({count/len(results)*100:.1f}%), "
              f"{success_rate:.1f}% success")
    
    # Final assessment
    print(f"\n{'='*70}")
    print(f"🎯 FINAL ASSESSMENT")
    print(f"{'='*70}")
    
    total_success_rate = (fully_successful + partial_success) / len(results) * 100
    
    meets_time = total_minutes <= 5.0
    meets_success = total_success_rate >= 90
    
    if meets_time and meets_success:
        print(f"\n✅ PRODUCTION READY!")
        print(f"   ✓ Completed 300 requests in {total_minutes:.2f} minutes")
        print(f"   ✓ Success rate: {total_success_rate:.1f}%")
        print(f"   ✓ Average speed: {avg_rps:.1f} RPS")
        print(f"\n🎉 System can handle peak load of 300 requests efficiently!")
        print(f"   Estimated capacity: {int(avg_rps * 60)} requests/minute")
    elif meets_time:
        print(f"\n⚠️  FAST BUT NEEDS RELIABILITY IMPROVEMENT")
        print(f"   ✓ Completed in time: {total_minutes:.2f} minutes")
        print(f"   ✗ Success rate: {total_success_rate:.1f}% (target: 90%+)")
        print(f"\n💡 Recommendations:")
        print(f"   • Review error patterns")
        print(f"   • Check image quality requirements")
        print(f"   • Verify prompt effectiveness")
    elif meets_success:
        print(f"\n⚠️  RELIABLE BUT NEEDS SPEED OPTIMIZATION")
        print(f"   ✗ Time: {total_minutes:.2f} minutes (target: 5.0)")
        print(f"   ✓ Success rate: {total_success_rate:.1f}%")
        print(f"\n💡 Recommendations:")
        print(f"   • Increase concurrent requests")
        print(f"   • Optimize network latency")
        print(f"   • Consider additional regions")
    else:
        print(f"\n❌ NEEDS OPTIMIZATION")
        print(f"   ✗ Time: {total_minutes:.2f} minutes (target: 5.0)")
        print(f"   ✗ Success rate: {total_success_rate:.1f}% (target: 90%+)")
        print(f"\n💡 Recommendations:")
        print(f"   • Review system configuration")
        print(f"   • Check quota limits")
        print(f"   • Analyze error patterns")
    
    # Cleanup
    await service.cleanup()
    
    print(f"\n{'='*70}")
    print(f"✨ TEST COMPLETE")
    print(f"{'='*70}\n")
    
    return {
        "total_time": total_time,
        "success_rate": total_success_rate,
        "avg_rps": avg_rps,
        "fully_successful": fully_successful,
        "errors": errors
    }

if __name__ == "__main__":
    asyncio.run(test_production_load())
