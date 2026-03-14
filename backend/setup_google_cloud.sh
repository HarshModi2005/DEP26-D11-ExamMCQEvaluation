#!/bin/bash
# Google Cloud Console Setup Script for Multi-Region OCR
# =====================================================
# This script sets up the necessary Google Cloud resources for 300+ RPS OCR processing

set -e

# Configuration
PROJECT_ID="project-75abf07c-e594-4660-ab7"
REGIONS=("us-central1" "us-east1" "us-west1" "europe-west1")
SERVICE_ACCOUNT_PREFIX="ocr-service"

echo "🚀 Setting up Google Cloud resources for Multi-Region OCR"
echo "Project ID: $PROJECT_ID"
echo "Regions: ${REGIONS[*]}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI is not installed. Please install it first:"
    echo "https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Set project
echo "📋 Setting project..."
gcloud config set project $PROJECT_ID

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable aiplatform.googleapis.com
gcloud services enable compute.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable drive.googleapis.com
gcloud services enable sheets.googleapis.com

echo "✅ APIs enabled successfully"

# Create service accounts for each region
echo "👤 Creating service accounts..."
mkdir -p sa-keys

for region in "${REGIONS[@]}"; do
    SA_NAME="${SERVICE_ACCOUNT_PREFIX}-${region}"
    SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
    KEY_FILE="sa-keys/${SA_NAME}.json"
    
    echo "  Creating service account: $SA_NAME"
    
    # Create service account
    gcloud iam service-accounts create $SA_NAME \
        --display-name="OCR Service Account for $region" \
        --description="Service account for multi-region OCR processing in $region" \
        || echo "Service account $SA_NAME already exists"
    
    # Grant necessary roles
    echo "  Granting roles to $SA_NAME..."
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/aiplatform.user"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/storage.objectViewer"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/drive.readonly"
    
    # Create and download key
    echo "  Creating key file: $KEY_FILE"
    gcloud iam service-accounts keys create $KEY_FILE \
        --iam-account=$SA_EMAIL \
        || echo "Key for $SA_NAME may already exist"
done

echo "✅ Service accounts created successfully"

# Display quota increase instructions
echo ""
echo "📊 QUOTA INCREASE REQUIRED"
echo "=========================="
echo "You need to request quota increases in the Google Cloud Console:"
echo ""
echo "1. Go to: https://console.cloud.google.com/iam-admin/quotas"
echo "2. Filter by 'Vertex AI API'"
echo "3. For EACH region (${REGIONS[*]}), request increases for:"
echo ""

for region in "${REGIONS[@]}"; do
    echo "   Region: $region"
    echo "   ├── Requests per minute: 6,000 (from ~60)"
    echo "   ├── Tokens per minute: 600,000 (from ~30,000)"
    echo "   └── Concurrent requests: 150 (from 100)"
    echo ""
done

echo "Justification text to use:"
echo "\"Implementing high-throughput OCR pipeline for educational assessment platform."
echo "Need to process 300+ answer sheets per second across multiple regions for"
echo "scalability and fault tolerance. Current limits prevent achieving required"
echo "throughput for production workload.\""
echo ""

# Create monitoring dashboard config
echo "📈 Creating monitoring configuration..."
cat > monitoring-dashboard.json << 'EOF'
{
  "displayName": "Multi-Region OCR Dashboard",
  "mosaicLayout": {
    "tiles": [
      {
        "width": 6,
        "height": 4,
        "widget": {
          "title": "OCR Requests per Second by Region",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"vertex_ai_endpoint\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_RATE"
                    }
                  }
                }
              }
            ]
          }
        }
      },
      {
        "width": 6,
        "height": 4,
        "xPos": 6,
        "widget": {
          "title": "Response Time by Model",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"vertex_ai_endpoint\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_MEAN"
                    }
                  }
                }
              }
            ]
          }
        }
      }
    ]
  }
}
EOF

echo "✅ Monitoring dashboard config created: monitoring-dashboard.json"

# Create deployment script
echo "🚀 Creating deployment script..."
cat > deploy_multi_region.sh << 'EOF'
#!/bin/bash
# Deploy OCR service to multiple regions

PROJECT_ID="project-75abf07c-e594-4660-ab7"
REGIONS=("us-central1" "us-east1" "us-west1" "europe-west1")

echo "🚀 Deploying OCR service to multiple regions..."

# Build the container image
echo "📦 Building container image..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/multi-region-ocr .

# Deploy to each region
for region in "${REGIONS[@]}"; do
    echo "🌍 Deploying to $region..."
    
    gcloud run deploy ocr-service-$region \
        --image gcr.io/$PROJECT_ID/multi-region-ocr \
        --region $region \
        --platform managed \
        --memory 4Gi \
        --cpu 2 \
        --concurrency 100 \
        --max-instances 20 \
        --min-instances 1 \
        --service-account ocr-service-$region@$PROJECT_ID.iam.gserviceaccount.com \
        --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT_ID,REGION=$region \
        --allow-unauthenticated
    
    echo "✅ Deployed to $region"
done

echo "🎉 Multi-region deployment complete!"
EOF

chmod +x deploy_multi_region.sh

# Create Dockerfile for Cloud Run deployment
echo "🐳 Creating Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy service account keys
COPY sa-keys/ sa-keys/

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
EOF

# Create requirements.txt for deployment
echo "📦 Creating requirements.txt..."
cat > requirements_multi_region.txt << 'EOF'
fastapi==0.104.1
uvicorn==0.24.0
aiohttp==3.9.1
google-cloud-aiplatform==1.38.1
google-auth==2.23.4
google-api-python-client==2.108.0
pydantic==2.5.0
python-multipart==0.0.6
prometheus-client==0.19.0
asyncio-throttle==1.0.2
EOF

# Create load balancer configuration
echo "⚖️ Creating load balancer configuration..."
cat > load_balancer_config.yaml << 'EOF'
# Google Cloud Load Balancer Configuration
# Use this as reference for manual setup in Console

backends:
  - name: ocr-backend-us-central1
    service: ocr-service-us-central1
    region: us-central1
    capacity_scaler: 1.0
    
  - name: ocr-backend-us-east1
    service: ocr-service-us-east1
    region: us-east1
    capacity_scaler: 1.0
    
  - name: ocr-backend-us-west1
    service: ocr-service-us-west1
    region: us-west1
    capacity_scaler: 1.0
    
  - name: ocr-backend-europe-west1
    service: ocr-service-europe-west1
    region: europe-west1
    capacity_scaler: 1.0

health_check:
  path: /api/batch/health
  interval: 30s
  timeout: 10s
  healthy_threshold: 2
  unhealthy_threshold: 3

load_balancing:
  policy: ROUND_ROBIN
  session_affinity: NONE
EOF

echo ""
echo "🎉 Google Cloud setup complete!"
echo ""
echo "📋 NEXT STEPS:"
echo "=============="
echo "1. Request quota increases (see instructions above)"
echo "2. Wait for quota approval (usually 1-2 business days)"
echo "3. Test the multi-region service:"
echo "   python -m pytest test_multi_region_ocr.py"
echo "4. Deploy to Cloud Run (optional):"
echo "   ./deploy_multi_region.sh"
echo ""
echo "📁 FILES CREATED:"
echo "├── sa-keys/ (service account keys)"
echo "├── monitoring-dashboard.json"
echo "├── deploy_multi_region.sh"
echo "├── Dockerfile"
echo "├── requirements_multi_region.txt"
echo "└── load_balancer_config.yaml"
echo ""
echo "🔗 USEFUL LINKS:"
echo "• Quotas: https://console.cloud.google.com/iam-admin/quotas"
echo "• Monitoring: https://console.cloud.google.com/monitoring"
echo "• Cloud Run: https://console.cloud.google.com/run"
echo "• Load Balancing: https://console.cloud.google.com/net-services/loadbalancing"
EOF

chmod +x setup_google_cloud.sh
