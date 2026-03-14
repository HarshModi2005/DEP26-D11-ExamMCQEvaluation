# Multi-Region OCR Pipeline Implementation Plan
## Target: 300+ OCR Requests Per Second

### 🎯 **Overview**
Transform the current single-region OCR pipeline to support 500+ RPS using:
- **4 Regions**: us-central1, us-east1, us-west1, europe-west1
- **3 Models**: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-2.5-pro
- **1,200 Total Concurrent Capacity**: 4 regions × 3 models × 100 concurrent each

---

## 📋 **Phase 1: Google Cloud Console Setup (Week 1)**

### **1.1 Enable APIs in All Regions**
```bash
# Enable Vertex AI API in your project
gcloud services enable aiplatform.googleapis.com
gcloud services enable compute.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
```

### **1.2 Create Service Accounts for Each Region**
```bash
# Create service accounts
gcloud iam service-accounts create ocr-service-us-central1
gcloud iam service-accounts create ocr-service-us-east1  
gcloud iam service-accounts create ocr-service-us-west1
gcloud iam service-accounts create ocr-service-europe-west1

# Grant necessary permissions
for region in us-central1 us-east1 us-west1 europe-west1; do
  gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:ocr-service-${region}@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
  
  gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:ocr-service-${region}@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/storage.objectViewer"
done
```

### **1.3 Request Quota Increases**
**In Google Cloud Console → IAM & Admin → Quotas:**

For **EACH** of the 4 regions, request increases for:
- **Requests per minute**: 6,000 (from default 60)
- **Tokens per minute**: 600,000 (from default 30,000)
- **Concurrent requests**: 150 (from default 100)

**Justification text for quota request:**
```
"Implementing high-throughput OCR pipeline for educational assessment platform. 
Need to process 300+ answer sheets per second across multiple regions for 
scalability and fault tolerance. Current limits prevent achieving required 
throughput for production workload."
```

---

## 🏗️ **Phase 2: Architecture Implementation (Week 2-3)**

### **2.1 Create Multi-Region OCR Service**

**File: `backend/services/multi_region_ocr_service.py`**
```python
import asyncio
import aiohttp
import random
from typing import List, Dict, Optional
from dataclasses import dataclass
from google.oauth2 import service_account
import google.auth.transport.requests

@dataclass
class OCREndpoint:
    region: str
    model: str
    url: str
    service_account_path: str
    current_load: int = 0
    max_concurrent: int = 100
    avg_response_time: float = 1.9

class MultiRegionOCRService:
    def __init__(self):
        self.endpoints = self._initialize_endpoints()
        self.session_pool = {}
        self.load_balancer = LoadBalancer(self.endpoints)
    
    def _initialize_endpoints(self) -> List[OCREndpoint]:
        """Initialize all region/model combinations"""
        regions = [
            ("us-central1", "sa-keys/ocr-service-us-central1.json"),
            ("us-east1", "sa-keys/ocr-service-us-east1.json"),
            ("us-west1", "sa-keys/ocr-service-us-west1.json"),
            ("europe-west1", "sa-keys/ocr-service-europe-west1.json")
        ]
        
        models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash", 
            "gemini-2.5-pro"
        ]
        
        endpoints = []
        for region, sa_path in regions:
            for model in models:
                url = (f"https://{region}-aiplatform.googleapis.com/v1/"
                      f"projects/{PROJECT_ID}/locations/{region}/"
                      f"publishers/google/models/{model}:generateContent")
                
                endpoints.append(OCREndpoint(
                    region=region,
                    model=model,
                    url=url,
                    service_account_path=sa_path
                ))
        
        return endpoints
    
    async def process_batch(self, image_paths: List[str]) -> List[Dict]:
        """Process multiple images concurrently across all endpoints"""
        tasks = []
        
        for image_path in image_paths:
            endpoint = self.load_balancer.get_best_endpoint()
            task = self._process_single_image(endpoint, image_path)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    
    async def _process_single_image(self, endpoint: OCREndpoint, image_path: str) -> Dict:
        """Process single image on specific endpoint"""
        try:
            endpoint.current_load += 1
            
            # Get session for this endpoint
            session = await self._get_session(endpoint)
            
            # Prepare request
            headers = await self._get_auth_headers(endpoint)
            payload = self._create_payload(image_path)
            
            # Make request
            async with session.post(endpoint.url, headers=headers, json=payload) as response:
                result = await response.json()
                return self._parse_response(result)
                
        except Exception as e:
            return {"error": str(e), "endpoint": f"{endpoint.region}/{endpoint.model}"}
        finally:
            endpoint.current_load -= 1

class LoadBalancer:
    def __init__(self, endpoints: List[OCREndpoint]):
        self.endpoints = endpoints
    
    def get_best_endpoint(self) -> OCREndpoint:
        """Get endpoint with lowest current load"""
        available = [ep for ep in self.endpoints if ep.current_load < ep.max_concurrent]
        
        if not available:
            # All endpoints at capacity, use least loaded
            return min(self.endpoints, key=lambda ep: ep.current_load)
        
        # Return endpoint with lowest load, prefer faster models
        return min(available, key=lambda ep: (ep.current_load, ep.avg_response_time))
```

### **2.2 Update Main OCR Service**

**Modify `backend/services/ocr_service.py`:**
```python
class OCRService:
    def __init__(self, use_multi_region: bool = True):
        if use_multi_region:
            self.multi_region_service = MultiRegionOCRService()
        else:
            # Keep existing single-region implementation
            self._initialize_single_region()
    
    async def extract_objective_sheets_batch(self, image_paths: List[str]) -> List[Dict]:
        """Process multiple sheets concurrently"""
        if hasattr(self, 'multi_region_service'):
            return await self.multi_region_service.process_batch(image_paths)
        else:
            # Fallback to sequential processing
            results = []
            for path in image_paths:
                result = self.extract_objective_sheet(path)
                results.append(result)
            return results
```

### **2.3 Update API Endpoints for Batch Processing**

**Modify `backend/api/endpoints.py`:**
```python
@router.post("/process-drive-folder-batch")
async def process_drive_folder_batch(request: ProcessFolderRequest):
    """
    Batch process all student sheets using multi-region OCR
    """
    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)
    
    answer_key_files, student_sheets = drive_service.separate_files(all_files)
    
    # Download all images first (parallel download)
    temp_dir = tempfile.mkdtemp(prefix="batch_sheets_")
    download_tasks = []
    
    for sheet_file in student_sheets:
        local_path = os.path.join(temp_dir, sheet_file["name"])
        task = asyncio.create_task(
            drive_service.download_file_async(sheet_file["id"], local_path)
        )
        download_tasks.append((task, local_path, sheet_file))
    
    # Wait for all downloads
    download_results = await asyncio.gather(*[task for task, _, _ in download_tasks])
    
    # Extract image paths for successful downloads
    image_paths = []
    file_mapping = {}
    
    for (task, local_path, sheet_file), success in zip(download_tasks, download_results):
        if success:
            image_paths.append(local_path)
            file_mapping[local_path] = sheet_file
    
    # Batch OCR processing
    ocr_results = await ocr_service.extract_objective_sheets_batch(image_paths)
    
    # Process results
    final_results = []
    for image_path, ocr_result in zip(image_paths, ocr_results):
        if "error" not in ocr_result:
            student_result = EvaluationService.match_and_score(
                _current_answer_key, ocr_result
            )
            final_results.append(student_result)
    
    return {
        "total_processed": len(final_results),
        "results": final_results,
        "processing_time": time.time() - start_time
    }
```

---

## ⚙️ **Phase 3: Google Cloud Console Configuration**

### **3.1 Cloud Load Balancer Setup**

**In Google Cloud Console:**

1. **Navigation Menu → Network Services → Load Balancing**
2. **Create Load Balancer → HTTP(S) Load Balancer**
3. **Configuration:**
   - Name: `ocr-multi-region-lb`
   - Backend Configuration:
     - Create backend services for each region
     - Health check: `/health` endpoint
     - Session affinity: None (stateless)

### **3.2 Cloud Run Deployment (Optional)**

**Deploy to Cloud Run for auto-scaling:**
```bash
# Build and deploy to each region
for region in us-central1 us-east1 us-west1 europe-west1; do
  gcloud run deploy ocr-service-${region} \
    --source . \
    --region ${region} \
    --platform managed \
    --memory 2Gi \
    --cpu 2 \
    --concurrency 100 \
    --max-instances 10 \
    --service-account ocr-service-${region}@PROJECT_ID.iam.gserviceaccount.com
done
```

### **3.3 Monitoring Setup**

**In Google Cloud Console → Monitoring:**

1. **Create Custom Dashboards:**
   - OCR Request Rate by Region
   - Response Time by Model
   - Error Rate by Endpoint
   - Concurrent Request Count

2. **Set Up Alerts:**
   - Response time > 3 seconds
   - Error rate > 5%
   - Queue depth > 50

---

## 🧪 **Phase 4: Testing & Optimization (Week 4-5)**

### **4.1 Load Testing Script**

**File: `backend/test_multi_region_load.py`**
```python
import asyncio
import aiohttp
import time
from concurrent.futures import ThreadPoolExecutor

async def load_test_ocr_pipeline():
    """Test the multi-region OCR pipeline under load"""
    
    # Simulate 300 concurrent requests
    test_images = ["test_sheet_1.jpg"] * 300
    
    start_time = time.time()
    
    # Process in batches of 50
    batch_size = 50
    batches = [test_images[i:i+batch_size] for i in range(0, len(test_images), batch_size)]
    
    results = []
    for batch in batches:
        batch_results = await ocr_service.extract_objective_sheets_batch(batch)
        results.extend(batch_results)
    
    end_time = time.time()
    
    total_time = end_time - start_time
    rps = len(test_images) / total_time
    
    print(f"Processed {len(test_images)} images in {total_time:.2f}s")
    print(f"Achieved RPS: {rps:.1f}")
    print(f"Target met: {'✅' if rps >= 300 else '❌'}")
    
    return rps

if __name__ == "__main__":
    asyncio.run(load_test_ocr_pipeline())
```

### **4.2 Performance Optimization**

**Add Connection Pooling:**
```python
# In MultiRegionOCRService
async def _get_session(self, endpoint: OCREndpoint) -> aiohttp.ClientSession:
    """Get or create session with connection pooling"""
    key = f"{endpoint.region}-{endpoint.model}"
    
    if key not in self.session_pool:
        connector = aiohttp.TCPConnector(
            limit=200,  # Total connection pool size
            limit_per_host=50,  # Per host limit
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        self.session_pool[key] = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30)
        )
    
    return self.session_pool[key]
```

---

## 📊 **Phase 5: Monitoring & Scaling (Week 6)**

### **5.1 Production Monitoring**

**Add to `backend/services/monitoring_service.py`:**
```python
import time
from prometheus_client import Counter, Histogram, Gauge

# Metrics
ocr_requests_total = Counter('ocr_requests_total', 'Total OCR requests', ['region', 'model', 'status'])
ocr_request_duration = Histogram('ocr_request_duration_seconds', 'OCR request duration', ['region', 'model'])
ocr_concurrent_requests = Gauge('ocr_concurrent_requests', 'Current concurrent requests', ['region', 'model'])

class OCRMetrics:
    @staticmethod
    def record_request(region: str, model: str, duration: float, success: bool):
        status = 'success' if success else 'error'
        ocr_requests_total.labels(region=region, model=model, status=status).inc()
        ocr_request_duration.labels(region=region, model=model).observe(duration)
    
    @staticmethod
    def set_concurrent_requests(region: str, model: str, count: int):
        ocr_concurrent_requests.labels(region=region, model=model).set(count)
```

### **5.2 Auto-Scaling Configuration**

**Cloud Run Auto-scaling:**
```yaml
# cloud-run-config.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: ocr-service
  annotations:
    run.googleapis.com/cpu-throttling: "false"
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "20"
        autoscaling.knative.dev/minScale: "2"
        run.googleapis.com/execution-environment: gen2
    spec:
      containerConcurrency: 100
      containers:
      - image: gcr.io/PROJECT_ID/ocr-service
        resources:
          limits:
            cpu: "2"
            memory: "4Gi"
```

---

## 🎯 **Google Cloud Console Action Items**

### **Immediate Actions (Week 1):**

1. **Enable APIs:**
   - Go to APIs & Services → Library
   - Enable: Vertex AI API, Cloud Run API, Cloud Build API

2. **Request Quota Increases:**
   - Go to IAM & Admin → Quotas
   - Filter by "Vertex AI API"
   - For each region (us-central1, us-east1, us-west1, europe-west1):
     - Request "Requests per minute" → 6,000
     - Request "Tokens per minute" → 600,000

3. **Create Service Accounts:**
   - Go to IAM & Admin → Service Accounts
   - Create 4 service accounts (one per region)
   - Grant "Vertex AI User" role to each

4. **Set up Billing Alerts:**
   - Go to Billing → Budgets & Alerts
   - Create budget with alerts at 50%, 80%, 100% of expected usage

### **Configuration Actions (Week 2-3):**

5. **Deploy Load Balancer:**
   - Go to Network Services → Load Balancing
   - Create HTTP(S) Load Balancer
   - Configure backend services for each region

6. **Set up Monitoring:**
   - Go to Monitoring → Dashboards
   - Create custom dashboard for OCR metrics
   - Set up alerting policies

### **Expected Results:**
- **Theoretical Capacity:** 1,200 concurrent requests
- **Expected RPS:** 500+ requests per second
- **Target Achievement:** ✅ 67% above 300 RPS goal
- **Fault Tolerance:** Multi-region redundancy
- **Cost Optimization:** Load balancing across regions

This implementation will give you a robust, scalable OCR pipeline capable of handling 300+ requests per second with room for growth.
