#!/usr/bin/env python3
"""
Optimized Multi-Region OCR Service for Peak Load
================================================
Target: Process 300 requests in 4-5 minutes (60-75 RPS sustained)

Optimizations:
1. Aggressive connection pooling with keep-alive
2. Parallel batch processing with optimal chunk sizes
3. Image compression and payload optimization
4. Smart retry logic with exponential backoff
5. Pre-warmed connections and token caching
6. Streaming responses where possible
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
from PIL import Image
import io
from services.image_preprocessing import preprocess_for_ocr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class OptimizedEndpoint:
    """Optimized endpoint with aggressive connection pooling"""
    region: str
    model: str
    url: str
    service_account_path: str
    project_id: str
    current_load: int = 0
    max_concurrent: int = 150  # Increased from 100
    avg_response_time: float = 2.0
    total_requests: int = 0
    total_errors: int = 0
    is_healthy: bool = True
    last_success: float = field(default_factory=time.time)

class OptimizedOCRService:
    """Highly optimized OCR service for peak loads"""
    
    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "project-5fa1c6c6-be40-41cd-b42")
        self.endpoints = self._initialize_endpoints()
        self.session_pool = {}
        self.credentials_cache = {}
        self.token_cache = {}
        self.token_expiry = {}
        
        # Optimization settings
        self.max_image_size = (1920, 1920)  # Resize large images
        self.jpeg_quality = 85  # Compression quality
        self.optimal_batch_size = 25  # Optimal chunk size for parallel processing
        self.connection_pool_size = 500  # Large connection pool
        
        logger.info(f"Initialized OptimizedOCRService with {len(self.endpoints)} endpoints")
        logger.info(f"Optimization: batch_size={self.optimal_batch_size}, pool_size={self.connection_pool_size}")
    
    def _initialize_endpoints(self) -> List[OptimizedEndpoint]:
        """Initialize endpoints with priority on fastest models"""
        regions = ["us-central1", "us-east1", "us-west1", "europe-west1"]
        
        # Prioritize fastest model
        models = [
            "gemini-2.5-flash",       # Primary - more capable than lite
            "gemini-2.5-flash-lite",  # Backup - faster but less capable
        ]
        
        endpoints = []
        base_sa_path = os.path.join(os.path.dirname(__file__), "..", "sa-keys")
        
        for region in regions:
            for model in models:
                url = (f"https://{region}-aiplatform.googleapis.com/v1/"
                      f"projects/{self.project_id}/locations/{region}/"
                      f"publishers/google/models/{model}:generateContent")
                
                sa_path = os.path.join(base_sa_path, f"ocr-service-{region}.json")
                if not os.path.exists(sa_path):
                    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_key.json")
                
                endpoints.append(OptimizedEndpoint(
                    region=region,
                    model=model,
                    url=url,
                    service_account_path=sa_path,
                    project_id=self.project_id
                ))
        
        return endpoints
    
    def _optimize_image(self, image_path: str) -> Tuple[str, str]:
        """
        Preprocess image for OCR: intelligently crop the white answer-sheet
        from the background, resize, and compress to JPEG.
        Delegates to the shared image_preprocessing utility.
        """
        image_bytes, mime_type = preprocess_for_ocr(
            image_path,
            max_size=self.max_image_size,
            jpeg_quality=self.jpeg_quality,
        )
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        return base64_image, mime_type
    
    async def process_batch_optimized(self, image_paths: List[str], 
                                     target_time_minutes: float = 5.0) -> List[Dict]:
        """
        Process batch with aggressive optimization for speed
        
        Args:
            image_paths: List of image paths
            target_time_minutes: Target completion time in minutes
        
        Returns:
            List of OCR results
        """
        total_images = len(image_paths)
        target_seconds = target_time_minutes * 60
        
        logger.info(f"Processing {total_images} images with target time: {target_time_minutes} minutes")
        
        # Calculate optimal concurrency
        # Target: Complete in target_seconds with avg 2s per request
        # Concurrent = (total_images * 2s) / target_seconds
        optimal_concurrent = min(
            int((total_images * 2.0) / target_seconds) + 10,  # Add buffer
            200  # Max safe concurrent
        )
        
        logger.info(f"Using {optimal_concurrent} concurrent requests for optimal speed")
        
        # Pre-warm connections
        await self._prewarm_connections()
        
        # Split into optimal chunks for parallel processing
        chunk_size = self.optimal_batch_size
        chunks = [image_paths[i:i+chunk_size] for i in range(0, len(image_paths), chunk_size)]
        
        logger.info(f"Split into {len(chunks)} chunks of ~{chunk_size} images each")
        
        # Process all chunks in parallel
        start_time = time.time()
        all_results = []
        
        # Create semaphore for global concurrency control
        semaphore = asyncio.Semaphore(optimal_concurrent)
        
        # Process all images across all chunks concurrently
        tasks = []
        for chunk_idx, chunk in enumerate(chunks):
            for img_idx, image_path in enumerate(chunk):
                global_idx = chunk_idx * chunk_size + img_idx
                task = asyncio.create_task(
                    self._process_single_optimized(semaphore, image_path, global_idx)
                )
                tasks.append(task)
        
        # Progress tracking
        completed = 0
        for task in asyncio.as_completed(tasks):
            result = await task
            all_results.append(result)
            completed += 1
            
            if completed % 50 == 0 or completed == total_images:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total_images - completed) / rate if rate > 0 else 0
                logger.info(f"Progress: {completed}/{total_images} ({completed/total_images*100:.1f}%) "
                          f"- Rate: {rate:.1f} req/s - ETA: {eta:.0f}s")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Sort results by original index
        all_results.sort(key=lambda x: x.get('index', 0))
        
        # Statistics
        successful = len([r for r in all_results if "error" not in r])
        errors = len([r for r in all_results if "error" in r])
        avg_rate = total_images / total_time if total_time > 0 else 0
        
        logger.info(f"Batch complete: {successful}/{total_images} successful in {total_time:.1f}s "
                   f"({avg_rate:.1f} req/s)")
        
        return all_results
    
    async def _prewarm_connections(self):
        """Pre-warm connection pools for all endpoints"""
        logger.info("Pre-warming connections...")
        
        # Create sessions for all endpoints
        for endpoint in self.endpoints[:4]:  # Warm up first 4 endpoints
            try:
                await self._get_session(endpoint)
                # Pre-fetch and cache tokens
                await self._get_auth_headers_cached(endpoint)
            except Exception as e:
                logger.warning(f"Failed to prewarm {endpoint.region}/{endpoint.model}: {e}")
        
        logger.info("Connection pre-warming complete")
    
    async def _process_single_optimized(self, semaphore: asyncio.Semaphore,
                                       image_path: str, index: int) -> Dict:
        """Process single image with optimizations"""
        async with semaphore:
            return await self._process_with_retry(image_path, index)
    
    async def _process_with_retry(self, image_path: str, index: int, 
                                  max_retries: int = 2) -> Dict:
        """Process with smart retry logic"""
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                endpoint = self._get_best_endpoint_fast()
                if not endpoint:
                    return {
                        "error": "No healthy endpoints available",
                        "image_path": image_path,
                        "index": index
                    }
                
                endpoint.current_load += 1
                endpoint.total_requests += 1
                
                start_time = time.time()
                
                # Get cached session and auth
                session = await self._get_session(endpoint)
                headers = await self._get_auth_headers_cached(endpoint)
                
                # Optimize image
                base64_image, mime_type = self._optimize_image(image_path)
                
                # Create minimal payload
                payload = {
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"text": self._get_minimal_prompt()},
                            {"inline_data": {"mime_type": mime_type, "data": base64_image}}
                        ]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": 1024,
                        "temperature": 0.0
                    }
                }
                
                # Make request with timeout
                async with session.post(endpoint.url, headers=headers, json=payload, 
                                      timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status == 200:
                        result_data = await response.json()
                        parsed_result = self._parse_ocr_response(result_data)
                        
                        duration = time.time() - start_time
                        endpoint.avg_response_time = (endpoint.avg_response_time * 0.9) + (duration * 0.1)
                        endpoint.last_success = time.time()
                        
                        return {
                            **parsed_result,
                            "processing_time": duration,
                            "endpoint": f"{endpoint.region}/{endpoint.model}",
                            "index": index
                        }
                    else:
                        error_text = await response.text()
                        last_error = f"HTTP {response.status}: {error_text[:100]}"
                        
                        if response.status == 429:  # Rate limit
                            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                            continue
                        
                        raise Exception(last_error)
            
            except asyncio.TimeoutError:
                last_error = "Timeout"
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
            
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
            
            finally:
                if endpoint:
                    endpoint.current_load -= 1
        
        # All retries failed
        if endpoint:
            endpoint.total_errors += 1
        
        return {
            "error": last_error,
            "image_path": image_path,
            "endpoint": f"{endpoint.region}/{endpoint.model}" if endpoint else "none",
            "index": index,
            "processing_time": time.time() - start_time if 'start_time' in locals() else 0
        }
    
    def _get_best_endpoint_fast(self) -> Optional[OptimizedEndpoint]:
        """Fast endpoint selection prioritizing flash-lite"""
        # Prioritize healthy flash-lite endpoints with low load
        flash_lite = [ep for ep in self.endpoints 
                     if ep.is_healthy and "flash-lite" in ep.model 
                     and ep.current_load < ep.max_concurrent]
        
        if flash_lite:
            return min(flash_lite, key=lambda ep: (ep.current_load, ep.avg_response_time))
        
        # Fallback to any healthy endpoint
        available = [ep for ep in self.endpoints 
                    if ep.is_healthy and ep.current_load < ep.max_concurrent]
        
        if available:
            return min(available, key=lambda ep: ep.current_load)
        
        # Last resort: least loaded endpoint
        return min(self.endpoints, key=lambda ep: ep.current_load) if self.endpoints else None
    
    async def _get_session(self, endpoint: OptimizedEndpoint) -> aiohttp.ClientSession:
        """Get or create optimized session with aggressive pooling"""
        key = f"{endpoint.region}-{endpoint.model}"
        
        if key not in self.session_pool:
            connector = aiohttp.TCPConnector(
                limit=self.connection_pool_size,
                limit_per_host=100,
                ttl_dns_cache=300,
                keepalive_timeout=60,
                enable_cleanup_closed=True,
                force_close=False
            )
            
            timeout = aiohttp.ClientTimeout(total=20, connect=5)
            
            self.session_pool[key] = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"Connection": "keep-alive"}
            )
        
        return self.session_pool[key]
    
    async def _get_auth_headers_cached(self, endpoint: OptimizedEndpoint) -> Dict[str, str]:
        """Get cached authentication headers with token reuse"""
        key = endpoint.service_account_path
        current_time = time.time()
        
        # Check if we have a valid cached token
        if key in self.token_cache and key in self.token_expiry:
            if current_time < self.token_expiry[key]:
                return {
                    "Authorization": f"Bearer {self.token_cache[key]}",
                    "Content-Type": "application/json"
                }
        
        # Need to refresh token
        if key not in self.credentials_cache:
            try:
                creds = service_account.Credentials.from_service_account_file(
                    key,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                self.credentials_cache[key] = creds
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
                return {"Content-Type": "application/json"}
        
        creds = self.credentials_cache[key]
        
        try:
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            
            # Cache token for 55 minutes (tokens valid for 60 minutes)
            self.token_cache[key] = creds.token
            self.token_expiry[key] = current_time + (55 * 60)
            
            return {
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json"
            }
        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            return {"Content-Type": "application/json"}
    
    def _get_minimal_prompt(self) -> str:
        """Minimal prompt for faster processing with comprehensive answer support"""
        return """Extract from this handwritten answer sheet and return JSON:
{"entry_number": "roll number", "name": "student name", "answers": {"1": "A", "2": "AC", "3": "A", "4": "1000", "5": "BD"}}

CRITICAL RULES for "answers":
- Keys are QUESTION NUMBERS (strings like "1", "2", "3").
- Values are what the STUDENT MARKED as their answer, NOT the question number.
- For MCQ/option questions: extract ONLY the letter(s) selected: "A", "B", "C", "D", or combinations like "AC", "BCD".
- For numerical questions: extract the number they wrote, e.g. "600", "1000", "2.5".
- IMPORTANT: If a student writes "3) A" or "(a) = 3" or "Qus3 → (a)", the answer for Q3 is "A", NOT "3".
- The digit after "=" or "→" following an option letter is IRRELEVANT — ignore it.
- If a student labels answers like "Qus1 → B", "Q2 600", use those labels to map to the right question number.
- If multiple options are circled/marked for a single-answer MCQ, set value to "MULTIPLE".
- Omit any question the student left completely blank.
- Do NOT include the question number as its own answer value.

Return ONLY valid JSON, no markdown, no explanation."""
    
    def _parse_ocr_response(self, result: Dict) -> Dict:
        """Fast OCR response parsing"""
        try:
            text_parts = []
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                text_parts.append(part["text"])
            
            extracted_text = "".join(text_parts)
            
            import re
            cleaned_text = re.sub(r'```json\s*|\s*```', '', extracted_text).strip()
            
            try:
                parsed = json.loads(cleaned_text)
            except json.JSONDecodeError:
                match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                else:
                    raise ValueError("No valid JSON found")
            
            return self._normalize_ocr_output(parsed)
            
        except Exception as e:
            return {"error": f"Parse failed: {str(e)}", "raw_response": str(result)[:200]}
    
    def _normalize_ocr_output(self, parsed: Dict) -> Dict:
        """Fast normalization"""
        result = {
            "entry_number": parsed.get("entry_number") or "",
            "name": parsed.get("name") or "",
            "comments": parsed.get("comments") or "",
            "answers": {}
        }
        
        raw_answers = parsed.get("answers", {})
        
        if isinstance(raw_answers, dict):
            for k, v in raw_answers.items():
                try:
                    q_num = str(int(k))
                    option = str(v).strip().upper()
                    # Handle 'X' or other unattempted markers — keep in dict so
                    # evaluation can explicitly categorize them as unattempted
                    if option in ('X', 'NONE', '-', 'NA', 'N/A', 'BLANK',
                                  'NOT ATTEMPTED', 'UNATTEMPTED'):
                        result["answers"][q_num] = option
                    else:
                        # Clean up "OPTION" prefix and patterns like "1 (A)"
                        if "OPTION" in option:
                            option = option.replace("OPTION", "").strip()
                        import re
                        paren_match = re.search(r'\(\s*([A-Da-d]+)\s*\)', option)
                        if paren_match:
                            option = paren_match.group(1).upper()
                        elif re.match(r'^\d+[\s.,:;\-]+([A-Da-d])\s*$', option):
                            option = re.match(r'^\d+[\s.,:;\-]+([A-Da-d])\s*$', option).group(1).upper()
                        result["answers"][q_num] = option
                except (ValueError, TypeError):
                    continue
        
        return result
    
    async def cleanup(self):
        """Cleanup resources"""
        for session in self.session_pool.values():
            await session.close()
        self.session_pool.clear()
        logger.info("OptimizedOCRService cleanup complete")
