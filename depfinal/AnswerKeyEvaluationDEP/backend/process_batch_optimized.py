#!/usr/bin/env python3
"""
Simple Script to Process Batch of Images with Optimized OCR
===========================================================
Usage:
    python3 process_batch_optimized.py <folder_path> [output_file]
    
Examples:
    python3 process_batch_optimized.py ./answer_sheets
    python3 process_batch_optimized.py ./answer_sheets results.json
"""

import asyncio
import sys
import os
import json
import glob
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.optimized_ocr_service import OptimizedOCRService

async def process_folder(folder_path: str, output_file: str = None):
    """Process all images in a folder"""
    
    # Find all images
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']
    image_paths = []
    
    for ext in image_extensions:
        pattern = os.path.join(folder_path, '**', ext)
        image_paths.extend(glob.glob(pattern, recursive=True))
    
    if not image_paths:
        print(f"❌ No images found in {folder_path}")
        return
    
    print(f"📸 Found {len(image_paths)} images")
    print(f"📂 Folder: {folder_path}")
    
    # Initialize service
    print(f"\n⚙️  Initializing optimized OCR service...")
    service = OptimizedOCRService()
    
    # Calculate target time (5 minutes for up to 300, scale up for more)
    target_minutes = max(5.0, len(image_paths) / 60)
    
    print(f"🎯 Target completion time: {target_minutes:.1f} minutes")
    print(f"\n🚀 Starting processing...\n")
    
    # Process
    results = await service.process_batch_optimized(
        image_paths,
        target_time_minutes=target_minutes
    )
    
    # Save results
    if output_file is None:
        output_file = "ocr_results.json"
    
    output_data = {
        "total_images": len(image_paths),
        "results": results,
        "summary": {
            "successful": len([r for r in results if "error" not in r]),
            "errors": len([r for r in results if "error" in r]),
        }
    }
    
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n💾 Results saved to: {output_file}")
    
    # Cleanup
    await service.cleanup()
    
    # Summary
    successful = output_data["summary"]["successful"]
    errors = output_data["summary"]["errors"]
    
    print(f"\n{'='*70}")
    print(f"✨ PROCESSING COMPLETE")
    print(f"{'='*70}")
    print(f"✅ Successful: {successful}/{len(image_paths)} ({successful/len(image_paths)*100:.1f}%)")
    print(f"❌ Errors: {errors}/{len(image_paths)} ({errors/len(image_paths)*100:.1f}%)")
    print(f"{'='*70}\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 process_batch_optimized.py <folder_path> [output_file]")
        print("\nExamples:")
        print("  python3 process_batch_optimized.py ./answer_sheets")
        print("  python3 process_batch_optimized.py ./answer_sheets results.json")
        sys.exit(1)
    
    folder_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(folder_path):
        print(f"❌ Error: Folder not found: {folder_path}")
        sys.exit(1)
    
    asyncio.run(process_folder(folder_path, output_file))

if __name__ == "__main__":
    main()
