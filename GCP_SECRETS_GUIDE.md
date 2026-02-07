# GCP Secret Management Guide for Multi-Agent AI Assistant

## 🔐 Storing API Keys in GCP

You have three API keys to manage:
1. OPENAI_API_KEY
2. WEATHER_API_KEY
3. AIRS_API_KEY

---

## Option 1: GCP Secret Manager (RECOMMENDED for Production)

### Step 1: Enable Secret Manager API

```bash
# Set your project ID
export GCP_PROJECT_ID="streamlit-ai-demo-project"  # Replace with your actual project ID
gcloud config set project ${GCP_PROJECT_ID}

# Enable Secret Manager API
gcloud services enable secretmanager.googleapis.com
```

### Step 2: Create Secrets

```bash
# Create OpenAI API Key secret
echo -n "your_openai_api_key_here" | \
gcloud secrets create OPENAI_API_KEY \
    --data-file=- \
    --replication-policy="automatic"

# Create Weather API Key secret
echo -n "your_weather_api_key_here" | \
gcloud secrets create WEATHER_API_KEY \
    --data-file=- \
    --replication-policy="automatic"

# Create AIRS API Key secret
echo -n "your_airs_api_key_here" | \
gcloud secrets create AIRS_API_KEY \
    --data-file=- \
    --replication-policy="automatic"
```

### Step 3: Grant Cloud Run Access to Secrets

```bash
# Get your Cloud Run service account
export SERVICE_ACCOUNT=$(gcloud run services describe streamlit-ai-demo \
    --region=asia-southeast1 \
    --format="value(spec.template.spec.serviceAccountName)")

# If no service account is set, use default compute service account
if [ -z "$SERVICE_ACCOUNT" ]; then
    PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
    SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

echo "Service Account: ${SERVICE_ACCOUNT}"

# Grant access to each secret
gcloud secrets add-iam-policy-binding OPENAI_API_KEY \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding WEATHER_API_KEY \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding AIRS_API_KEY \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"
```

### Step 4: Update Cloud Run to Use Secrets

```bash
# Deploy with secrets mounted as environment variables
gcloud run deploy streamlit-ai-demo \
    --region=asia-southeast1 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"
```

### Step 5: Verify Secrets Are Available

```bash
# Check Cloud Run configuration
gcloud run services describe streamlit-ai-demo \
    --region=asia-southeast1 \
    --format="yaml(spec.template.spec.containers[0].env)"
```

---

## Option 2: Environment Variables (Simpler, Less Secure)

### Set Environment Variables in Cloud Run

```bash
# Deploy with environment variables (NOT RECOMMENDED for production)
gcloud run deploy streamlit-ai-demo \
    --region=asia-southeast1 \
    --set-env-vars="OPENAI_API_KEY=sk-your-key,WEATHER_API_KEY=your-key,AIRS_API_KEY=your-key"
```

**⚠️ WARNING**: Environment variables are visible in:
- Cloud Console
- gcloud describe commands
- Service configuration exports

---

## Option 3: Using .env File (Local Development Only)

### For Local Testing

```bash
# Create .env file in your project root
cat > .env << EOF
OPENAI_API_KEY=sk-your-openai-key-here
WEATHER_API_KEY=your-weather-key-here
AIRS_API_KEY=your-airs-key-here
EOF

# Make sure .env is in .gitignore
echo ".env" >> .gitignore

# Run locally
streamlit run app.py
```

---

## 🔄 Updating Secrets

### Update Existing Secret

```bash
# Add new version to secret
echo -n "new_api_key_value" | \
gcloud secrets versions add AIRS_API_KEY --data-file=-

# Cloud Run will automatically use latest version
# Or redeploy to force update
gcloud run services update streamlit-ai-demo --region=asia-southeast1
```

### View Secret Metadata (Not the Value)

```bash
# List all secrets
gcloud secrets list

# View secret details
gcloud secrets describe AIRS_API_KEY

# List versions
gcloud secrets versions list AIRS_API_KEY
```

### Access Secret Value (For Testing)

```bash
# Access latest version
gcloud secrets versions access latest --secret="AIRS_API_KEY"
```

---

## 🧪 Testing Secret Access

### Test from Cloud Run Container

```bash
# SSH into a Cloud Run instance (if possible)
# Or check logs for environment variables

# View Cloud Run logs
gcloud run logs read --service=streamlit-ai-demo --region=asia-southeast1 --limit=50
```

### Test Locally with Secrets

```bash
# Install gcloud Python library
pip install google-cloud-secret-manager

# Test script
python << EOF
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient()
project_id = "YOUR_PROJECT_ID"
secret_id = "AIRS_API_KEY"

name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
response = client.access_secret_version(request={"name": name})
secret_value = response.payload.data.decode("UTF-8")

print(f"Secret retrieved: {secret_value[:10]}...")  # Only show first 10 chars
EOF
```

---

## 📋 Complete Deployment Script with Secrets

```bash
#!/bin/bash

# Configuration
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="asia-southeast1"
export SERVICE_NAME="streamlit-ai-demo"
export IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}"

# Set project
gcloud config set project ${GCP_PROJECT_ID}

# Build image
echo "Building Docker image..."
gcloud builds submit --tag ${IMAGE_NAME}

# Deploy with secrets
echo "Deploying to Cloud Run with secrets..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${GCP_REGION} \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"

echo "Deployment complete!"

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${GCP_REGION} \
    --format="value(status.url)")

echo "Service URL: ${SERVICE_URL}"
```

---

## 🔒 Security Best Practices

### ✅ DO:
- Use Secret Manager for production
- Rotate secrets regularly (every 90 days)
- Grant least-privilege IAM permissions
- Use separate secrets for dev/staging/prod
- Enable audit logging for secret access
- Add secrets to .gitignore

### ❌ DON'T:
- Hardcode secrets in code
- Commit secrets to Git
- Share secrets via email/chat
- Use same secrets across environments
- Log secret values
- Store secrets in environment variables (production)

---

## 🔍 Troubleshooting

### Issue: "Permission denied" accessing secret

```bash
# Check IAM permissions
gcloud secrets get-iam-policy AIRS_API_KEY

# Grant access if missing
gcloud secrets add-iam-policy-binding AIRS_API_KEY \
    --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor"
```

### Issue: Cloud Run not picking up secrets

```bash
# Force redeploy
gcloud run services update streamlit-ai-demo \
    --region=asia-southeast1 \
    --clear-env-vars \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"
```

### Issue: Secret not found

```bash
# Verify secret exists
gcloud secrets describe AIRS_API_KEY

# Create if missing
echo -n "your_key" | gcloud secrets create AIRS_API_KEY --data-file=-
```

---

## 📊 Monitoring Secret Access

### Enable Audit Logging

```bash
# View audit logs for secret access
gcloud logging read \
    "resource.type=secretmanager.googleapis.com/Secret" \
    --limit=50 \
    --format=json
```

### Set Up Alerts

1. Go to Cloud Console → Monitoring → Alerting
2. Create alert for:
   - Failed secret access attempts
   - Unusual access patterns
   - Secret modifications

---

## 🚀 Quick Reference

```bash
# Create secret
echo -n "VALUE" | gcloud secrets create NAME --data-file=-

# Update secret
echo -n "NEW_VALUE" | gcloud secrets versions add NAME --data-file=-

# Grant access
gcloud secrets add-iam-policy-binding NAME \
    --member="serviceAccount:SA@PROJECT.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

# Deploy with secrets
gcloud run deploy SERVICE \
    --set-secrets="ENV_VAR=SECRET_NAME:latest"

# View secret value
gcloud secrets versions access latest --secret="NAME"

# Delete secret
gcloud secrets delete NAME
```

---

**Security Level Comparison:**

| Method | Security | Ease of Use | Cost | Recommended For |
|--------|----------|-------------|------|-----------------|
| Secret Manager | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | $ | Production |
| Env Variables | ⭐⭐ | ⭐⭐⭐⭐⭐ | Free | Development |
| .env File | ⭐ | ⭐⭐⭐⭐⭐ | Free | Local Only |

**Always use Secret Manager for production deployments!**
