#!/usr/bin/env python3
"""
Multi-Region OCR Service for High-Throughput Processing
=======================================================
Supports 300+ OCR requests per second using:
- 4 Regions: us-central1, us-east1, us-west1, europe-west1
- 3 Models: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-2.5-pro
- Load balancing and fault tolerance
"""

import asyncio
import aiohttp
import os
import json
import base64
import time
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from google.oauth2 import service_account
import google.auth.transport.requests
from services.image_preprocessing import preprocess_for_ocr

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class OCREndpoint:
    """Represents a single OCR endpoint (region + model combination)"""
    region: str
    model: str
    url: str
    service_account_path: str
    project_id: str
    current_load: int = 0
    max_concurrent: int = 100
    avg_response_time: float = 1.9
    total_requests: int = 0
    total_errors: int = 0
    last_health_check: float = field(default_factory=time.time)
    is_healthy: bool = True

class LoadBalancer:
    """Intelligent load balancer for OCR endpoints"""
    
    def __init__(self, endpoints: List[OCREndpoint]):
        self.endpoints = endpoints
        self.model_priority = {
            "gemini-2.5-flash": 1,       # Primary - balanced speed and capability
            "gemini-2.5-flash-lite": 2,  # Backup - faster but less capable
            "gemini-2.5-pro": 3          # Most capable
        }
    
    def get_best_endpoint(self) -> Optional[OCREndpoint]:
        """Get the best available endpoint based on load and performance"""
        # Filter healthy endpoints with available capacity
        available = [
            ep for ep in self.endpoints 
            if ep.is_healthy and ep.current_load < ep.max_concurrent
        ]
        
        if not available:
            # All at capacity, find least loaded healthy endpoint
            healthy = [ep for ep in self.endpoints if ep.is_healthy]
            if not healthy:
                logger.error("No healthy endpoints available!")
                return None
            return min(healthy, key=lambda ep: ep.current_load)
        
        # Score endpoints based on load, response time, and model priority
        def score_endpoint(ep: OCREndpoint) -> float:
            load_factor = ep.current_load / ep.max_concurrent
            time_factor = ep.avg_response_time / 2.0  # Normalize to ~1.0
            priority_factor = self.model_priority.get(ep.model, 4) / 4.0
            error_rate = ep.total_errors / max(ep.total_requests, 1)
            
            # Lower score is better
            return load_factor + time_factor + priority_factor + error_rate
        
        return min(available, key=score_endpoint)
    
    def get_endpoint_stats(self) -> Dict:
        """Get statistics for all endpoints"""
        stats = {
            "total_endpoints": len(self.endpoints),
            "healthy_endpoints": len([ep for ep in self.endpoints if ep.is_healthy]),
            "total_load": sum(ep.current_load for ep in self.endpoints),
            "max_capacity": sum(ep.max_concurrent for ep in self.endpoints),
            "by_region": {},
            "by_model": {}
        }
        
        for ep in self.endpoints:
            # By region
            if ep.region not in stats["by_region"]:
                stats["by_region"][ep.region] = {"load": 0, "capacity": 0, "healthy": 0}
            stats["by_region"][ep.region]["load"] += ep.current_load
            stats["by_region"][ep.region]["capacity"] += ep.max_concurrent
            if ep.is_healthy:
                stats["by_region"][ep.region]["healthy"] += 1
            
            # By model
            if ep.model not in stats["by_model"]:
                stats["by_model"][ep.model] = {"load": 0, "capacity": 0, "healthy": 0}
            stats["by_model"][ep.model]["load"] += ep.current_load
            stats["by_model"][ep.model]["capacity"] += ep.max_concurrent
            if ep.is_healthy:
                stats["by_model"][ep.model]["healthy"] += 1
        
        return stats

class MultiRegionOCRService:
    """High-throughput multi-region OCR service"""
    
    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "developmentengineeringproject")
        self.endpoints = self._initialize_endpoints()
        self.load_balancer = LoadBalancer(self.endpoints)
        self.session_pool = {}
        self.credentials_cache = {}
        
        logger.info(f"Initialized MultiRegionOCRService with {len(self.endpoints)} endpoints")
    
    def _initialize_endpoints(self) -> List[OCREndpoint]:
        """Initialize all region/model combinations"""
        regions = [
            "us-central1",
            "us-east1", 
            "us-west1",
            "europe-west1"
        ]
        
        models = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro"
        ]
        
        endpoints = []
        base_sa_path = os.path.join(os.path.dirname(__file__), "..", "sa-keys")
        
        for region in regions:
            for model in models:
                url = (f"https://{region}-aiplatform.googleapis.com/v1/"
                      f"projects/{self.project_id}/locations/{region}/"
                      f"publishers/google/models/{model}:generateContent")
                
                sa_path = os.path.join(base_sa_path, f"ocr-service-{region}.json")
                
                # Use default service account if region-specific doesn't exist
                if not os.path.exists(sa_path):
                    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_key.json")
                
                endpoints.append(OCREndpoint(
                    region=region,
                    model=model,
                    url=url,
                    service_account_path=sa_path,
                    project_id=self.project_id
                ))
        
        return endpoints
    
    async def process_batch(self, image_paths: List[str], max_concurrent: int = 300) -> List[Dict]:
        """
        Process multiple images concurrently across all endpoints
        
        Args:
            image_paths: List of image file paths to process
            max_concurrent: Maximum concurrent requests (default: 300)
        
        Returns:
            List of OCR results in same order as input
        """
        if not image_paths:
            return []
        
        logger.info(f"Processing batch of {len(image_paths)} images with max_concurrent={max_concurrent}")
        
        # Create semaphore to limit total concurrent requests
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Create tasks for all images
        tasks = []
        for i, image_path in enumerate(image_paths):
            task = asyncio.create_task(
                self._process_single_image_with_semaphore(semaphore, image_path, i)
            )
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error processing image {i}: {result}")
                processed_results.append({
                    "error": str(result),
                    "image_path": image_paths[i] if i < len(image_paths) else "unknown"
                })
            else:
                processed_results.append(result)
        
        success_count = len([r for r in processed_results if "error" not in r])
        logger.info(f"Batch processing complete: {success_count}/{len(image_paths)} successful")
        
        return processed_results
    
    async def _process_single_image_with_semaphore(self, semaphore: asyncio.Semaphore, 
                                                  image_path: str, index: int) -> Dict:
        """Process single image with semaphore control"""
        async with semaphore:
            return await self._process_single_image(image_path, index)
    
    async def _process_single_image(self, image_path: str, index: int = 0) -> Dict:
        """Process single image on best available endpoint"""
        start_time = time.time()
        endpoint = None
        
        try:
            # Get best endpoint
            endpoint = self.load_balancer.get_best_endpoint()
            if not endpoint:
                return {
                    "error": "No healthy endpoints available",
                    "image_path": image_path,
                    "index": index
                }
            
            # Update load
            endpoint.current_load += 1
            endpoint.total_requests += 1
            
            # Get session and credentials
            session = await self._get_session(endpoint)
            headers = await self._get_auth_headers(endpoint)
            
            # Prepare payload
            payload = self._create_ocr_payload(image_path)
            
            # Make request
            async with session.post(endpoint.url, headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    result_data = await response.json()
                    parsed_result = self._parse_ocr_response(result_data)
                    
                    # Update endpoint stats
                    duration = time.time() - start_time
                    endpoint.avg_response_time = (endpoint.avg_response_time * 0.9) + (duration * 0.1)
                    
                    return {
                        **parsed_result,
                        "processing_time": duration,
                        "endpoint": f"{endpoint.region}/{endpoint.model}",
                        "index": index
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text[:200]}")
        
        except Exception as e:
            if endpoint:
                endpoint.total_errors += 1
                # Mark unhealthy if error rate is too high
                error_rate = endpoint.total_errors / endpoint.total_requests
                if error_rate > 0.1:  # 10% error rate threshold
                    endpoint.is_healthy = False
                    logger.warning(f"Endpoint {endpoint.region}/{endpoint.model} marked unhealthy (error rate: {error_rate:.2%})")
            
            return {
                "error": str(e),
                "image_path": image_path,
                "endpoint": f"{endpoint.region}/{endpoint.model}" if endpoint else "none",
                "index": index,
                "processing_time": time.time() - start_time
            }
        
        finally:
            if endpoint:
                endpoint.current_load -= 1
    
    async def _get_session(self, endpoint: OCREndpoint) -> aiohttp.ClientSession:
        """Get or create session with connection pooling for endpoint"""
        key = f"{endpoint.region}-{endpoint.model}"
        
        if key not in self.session_pool:
            connector = aiohttp.TCPConnector(
                limit=200,  # Total connection pool size
                limit_per_host=50,  # Per host limit
                keepalive_timeout=30,
                enable_cleanup_closed=True,
                ssl=False  # Disable SSL verification for faster connections
            )
            
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            self.session_pool[key] = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
        
        return self.session_pool[key]
    
    async def _get_auth_headers(self, endpoint: OCREndpoint) -> Dict[str, str]:
        """Get authentication headers for endpoint"""
        key = endpoint.service_account_path
        
        # Cache credentials to avoid repeated file reads
        if key not in self.credentials_cache:
            try:
                creds = service_account.Credentials.from_service_account_file(
                    key,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                self.credentials_cache[key] = creds
            except Exception as e:
                logger.error(f"Failed to load credentials from {key}: {e}")
                return {"Content-Type": "application/json"}
        
        creds = self.credentials_cache[key]
        
        # Refresh token if needed
        try:
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            
            return {
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json"
            }
        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            return {"Content-Type": "application/json"}
    
    def _create_ocr_payload(self, image_path: str) -> Dict:
        """
        Create OCR request payload.
        The image is preprocessed (white-paper region detected, cropped,
        resized and compressed) before encoding to save bandwidth and improve
        OCR accuracy by removing non-paper background noise.
        """
        # Preprocess: crop to paper region, resize, JPEG-compress
        image_bytes, mime_type = preprocess_for_ocr(image_path)
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": self._get_ocr_prompt()},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.0
            }
        }
    
    def _get_ocr_prompt(self) -> str:
        """Get OCR prompt for objective answer sheets"""
        return """You are analyzing a HANDWRITTEN OBJECTIVE answer sheet (MCQ/OMR style).

Extract ONLY the following fields and return as valid JSON (no markdown):

{
    "entry_number": "the student's entry/roll number",
    "name": "the student's name",
    "answers": {
        "1": "BD",
        "2": "600",
        "3": "A",
        "4": "1000",
        "5": "BD"
    },
    "comments": "Any observations about the sheet quality or issues"
}

CRITICAL RULES for \"answers\":
- Keys are QUESTION NUMBERS (strings: "1", "2", "3", "4", "5").
- Values are what the STUDENT MARKED as their answer, NOT the question number.
- For MCQ/option questions: extract ONLY the letter(s) the student selected: "A", "B", "C", "D", or combinations like "AC", "BCD".
- For numerical questions: extract the number they wrote, e.g. "600", "1000", "2.5".
- IMPORTANT: If a student writes "3) A" or "(a) = 3" or "Qus3 → (a)" or "(a) → 3", the answer for Q3 is "A", NOT "3". The number after "=" or "→" following an option letter is the student's calculation/working — IGNORE IT.
- If a student labels answers like "Qus1 → B and D", "Q2 600", map them correctly to question numbers "1", "2", etc.
- If multiple options are circled/boxed for a single MCQ, set value to "MULTIPLE".
- Omit any question the student left completely blank.
- Do NOT output the question number itself as the answer value.
- "entry_number": Look for roll number, entry number, enrollment number, student ID.
- "name": The student's name as written on the sheet.
- If entry_number or name not found, set to null.

Return ONLY valid JSON, no explanation, no markdown.
"""
    
    def _parse_ocr_response(self, result: Dict) -> Dict:
        """Parse OCR response from Vertex AI"""
        try:
            # Extract text from response
            text_parts = []
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                text_parts.append(part["text"])
            
            extracted_text = "".join(text_parts)
            
            # Parse JSON from text
            import re
            # Remove markdown code blocks
            cleaned_text = re.sub(r'```json\s*|\s*```', '', extracted_text).strip()
            
            try:
                parsed = json.loads(cleaned_text)
            except json.JSONDecodeError:
                # Try to find JSON object in text
                match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                else:
                    raise ValueError("No valid JSON found in response")
            
            # Normalize the output
            return self._normalize_ocr_output(parsed)
            
        except Exception as e:
            return {
                "error": f"Failed to parse OCR response: {str(e)}",
                "raw_response": str(result)[:500]
            }
    
    def _normalize_ocr_output(self, parsed: Dict) -> Dict:
        """Normalize OCR output to expected format"""
        result = {
            "entry_number": parsed.get("entry_number") or parsed.get("roll_number") or "",
            "name": parsed.get("name") or parsed.get("student_name") or "", 
            "comments": parsed.get("comments") or "",
            "answers": {}
        }
        
        # Handle answers in different formats
        raw_answers = parsed.get("answers", {})
        
        if isinstance(raw_answers, dict):
            # Already a dict - normalize keys and values
            for k, v in raw_answers.items():
                try:
                    q_num = str(int(k))
                    option = str(v).strip().upper()
                    if "OPTION" in option:
                        option = option.replace("OPTION", "").strip()
                    # Handle 'X' or other unattempted markers — keep in dict so
                    # evaluation can explicitly categorize them as unattempted
                    if option in ('X', 'NONE', '-', 'NA', 'N/A', 'BLANK',
                                  'NOT ATTEMPTED', 'UNATTEMPTED'):
                        result["answers"][q_num] = option
                    else:
                        # Clean up patterns like "1 (A)", "(A)", "ANS 1 (A) 3"
                        import re
                        paren_match = re.search(r'\(\s*([A-Da-d]+)\s*\)', option)
                        if paren_match:
                            option = paren_match.group(1).upper()
                        elif re.match(r'^\d+[\s.,:;\-]+([A-Da-d])\s*$', option):
                            option = re.match(r'^\d+[\s.,:;\-]+([A-Da-d])\s*$', option).group(1).upper()
                        result["answers"][q_num] = option
                except (ValueError, TypeError):
                    continue
        
        elif isinstance(raw_answers, list):
            # List of dicts like [{"question_number": 1, "marked_option": "A"}, ...]
            for item in raw_answers:
                if isinstance(item, dict):
                    q_num = item.get("question_number")
                    option = item.get("marked_option") or item.get("option") or item.get("answer")
                    if q_num is not None and option:
                        result["answers"][str(int(q_num))] = str(option).strip().upper()
        
        return result
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return self.load_balancer.get_endpoint_stats()
    
    async def health_check(self) -> Dict:
        """Perform health check on all endpoints"""
        health_results = {}
        
        for endpoint in self.endpoints:
            key = f"{endpoint.region}/{endpoint.model}"
            try:
                # Simple health check - try to get auth headers
                headers = await self._get_auth_headers(endpoint)
                if "Authorization" in headers:
                    endpoint.is_healthy = True
                    endpoint.last_health_check = time.time()
                    health_results[key] = "healthy"
                else:
                    endpoint.is_healthy = False
                    health_results[key] = "auth_failed"
            except Exception as e:
                endpoint.is_healthy = False
                health_results[key] = f"error: {str(e)}"
        
        return health_results
    
    async def cleanup(self):
        """Cleanup resources"""
        for session in self.session_pool.values():
            await session.close()
        self.session_pool.clear()
        logger.info("MultiRegionOCRService cleanup complete")

# Example usage
async def main():
    """Example usage of MultiRegionOCRService"""
    service = MultiRegionOCRService()
    
    # Health check
    health = await service.health_check()
    print("Health check results:", health)
    
    # Process batch (example)
    # image_paths = ["test1.jpg", "test2.jpg", "test3.jpg"]
    # results = await service.process_batch(image_paths, max_concurrent=50)
    # print(f"Processed {len(results)} images")
    
    # Get stats
    stats = service.get_stats()
    print("Service stats:", stats)
    
    # Cleanup
    await service.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
