#!/bin/bash

# Deploy Multi-Agent AI Assistant with correct naming
# This creates a NEW service named "multi-agent-ai-assistant"

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
GCP_PROJECT_ID="${GCP_PROJECT_ID}"
GCP_REGION="asia-southeast1"
OLD_SERVICE="streamlit-ai-demo"
NEW_SERVICE="multi-agent-ai-assistant"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${NEW_SERVICE}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploying Multi-Agent AI Assistant${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check PROJECT_ID
if [ -z "$GCP_PROJECT_ID" ]; then
    echo -e "${RED}Error: GCP_PROJECT_ID not set${NC}"
    echo "Run: export GCP_PROJECT_ID=your-project-id"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project: ${GCP_PROJECT_ID}"
echo "  Region: ${GCP_REGION}"
echo "  Old Service: ${OLD_SERVICE}"
echo "  New Service: ${NEW_SERVICE}"
echo ""

# Set project
gcloud config set project ${GCP_PROJECT_ID}

# Enable APIs
echo -e "${YELLOW}Enabling required APIs...${NC}"
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Build new image
echo -e "${YELLOW}Building Docker image as ${IMAGE_NAME}...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Image built successfully${NC}"

# Check if secrets exist
echo -e "${YELLOW}Checking for secrets...${NC}"
SECRETS_EXIST=true

for SECRET in OPENAI_API_KEY WEATHER_API_KEY AIRS_API_KEY; do
    if ! gcloud secrets describe $SECRET &> /dev/null; then
        echo -e "${RED}✗ Secret $SECRET not found${NC}"
        SECRETS_EXIST=false
    else
        echo -e "${GREEN}✓ Secret $SECRET found${NC}"
    fi
done

if [ "$SECRETS_EXIST" = false ]; then
    echo ""
    echo -e "${RED}Error: Missing secrets. Create them first:${NC}"
    echo ""
    echo "echo -n 'your_openai_key' | gcloud secrets create OPENAI_API_KEY --data-file=-"
    echo "echo -n 'your_weather_key' | gcloud secrets create WEATHER_API_KEY --data-file=-"
    echo "echo -n 'your_airs_key' | gcloud secrets create AIRS_API_KEY --data-file=-"
    echo ""
    exit 1
fi

# Grant access to new service (preemptively)
echo -e "${YELLOW}Granting secret access...${NC}"
PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in OPENAI_API_KEY WEATHER_API_KEY AIRS_API_KEY; do
    gcloud secrets add-iam-policy-binding $SECRET \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor" \
        2>/dev/null || true
done

echo -e "${GREEN}✓ IAM permissions configured${NC}"

# Deploy new service
echo -e "${YELLOW}Deploying ${NEW_SERVICE}...${NC}"
gcloud run deploy ${NEW_SERVICE} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${GCP_REGION} \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Deployment failed${NC}"
    exit 1
fi

# Get new service URL
NEW_URL=$(gcloud run services describe ${NEW_SERVICE} --region ${GCP_REGION} --format="value(status.url)")

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Successful!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}New Service URL:${NC}"
echo -e "  ${BLUE}${NEW_URL}${NC}"
echo ""

# Check if old service exists
if gcloud run services describe ${OLD_SERVICE} --region ${GCP_REGION} &> /dev/null; then
    OLD_URL=$(gcloud run services describe ${OLD_SERVICE} --region ${GCP_REGION} --format="value(status.url)")
    echo -e "${YELLOW}Old Service Still Running:${NC}"
    echo -e "  ${OLD_URL}"
    echo ""
    echo -e "${YELLOW}To delete the old service, run:${NC}"
    echo -e "  gcloud run services delete ${OLD_SERVICE} --region ${GCP_REGION}"
    echo ""
fi

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. ${BLUE}Test New Service:${NC}"
echo "   ${NEW_URL}"
echo ""
echo "2. ${BLUE}Update Strata Cloud Manager:${NC}"
echo "   - Application: multi-agent-ai-assistant"
echo "   - URL: ${NEW_URL}"
echo "   - Security Profile: Jerry_AI_Security_Profile ✓"
echo "   - Deployment Profile: Jerry_AI_Demo ✓"
echo ""
echo "3. ${BLUE}Verify Security Working:${NC}"
echo "   - Check app sidebar for security status"
echo "   - Run test queries"
echo "   - Monitor in SCM dashboard"
echo ""
echo "4. ${BLUE}Delete Old Service (after testing):${NC}"
echo "   gcloud run services delete ${OLD_SERVICE} --region ${GCP_REGION}"
echo ""
echo -e "${GREEN}Done!${NC}"
