# Renaming GCP Cloud Run Service Guide
## From "streamlit-ai-demo" to "multi-agent-ai-assistant"

---

## 🎯 Goal

Update your GCP Cloud Run service name to match SCM:
- **Current**: `streamlit-ai-demo`
- **New**: `multi-agent-ai-assistant`

---

## 📋 Method: Deploy New Service (RECOMMENDED)

This is the **safest** approach with zero downtime.

### Step 1: Set Your Project ID

```bash
# Replace with your actual project ID
export GCP_PROJECT_ID="your-project-id-here"

# Verify it's set
echo "Project ID: ${GCP_PROJECT_ID}"

# Set as active project
gcloud config set project ${GCP_PROJECT_ID}
```

### Step 2: Verify Secrets Exist

```bash
# Check for secrets
gcloud secrets list | grep -E "OPENAI_API_KEY|WEATHER_API_KEY|AIRS_API_KEY"
```

**If secrets are missing, create them:**

```bash
# Create OpenAI secret
echo -n "your_openai_api_key_here" | \
  gcloud secrets create OPENAI_API_KEY --data-file=-

# Create Weather secret
echo -n "your_weather_api_key_here" | \
  gcloud secrets create WEATHER_API_KEY --data-file=-

# Create AIRS secret
echo -n "your_airs_api_key_here" | \
  gcloud secrets create AIRS_API_KEY --data-file=-

# Grant access to compute service account
PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in OPENAI_API_KEY WEATHER_API_KEY AIRS_API_KEY; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"
done
```

### Step 3: Build New Docker Image

```bash
# Navigate to your project directory
cd /path/to/your/project

# Build with new name
gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant

# This will take a few minutes
```

### Step 4: Deploy New Service

```bash
# Deploy to Cloud Run with new name
gcloud run deploy multi-agent-ai-assistant \
    --image gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant \
    --platform managed \
    --region asia-southeast1 \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"
```

### Step 5: Get New Service URL

```bash
# Get the new URL
NEW_URL=$(gcloud run services describe multi-agent-ai-assistant \
    --region asia-southeast1 \
    --format="value(status.url)")

echo "🎉 New Service URL: ${NEW_URL}"

# Example output:
# https://multi-agent-ai-assistant-959300415442.asia-southeast1.run.app
```

### Step 6: Test New Service

**Open the new URL in your browser and verify:**

1. ✅ App loads correctly
2. ✅ Enter API keys in sidebar
3. ✅ Click "🚀 Initialize Assistant"
4. ✅ See message: "🔒 AIRS connection healthy"
5. ✅ Security Settings section visible
6. ✅ Run test query: "What events are today?"
7. ✅ Check sidebar: Security Statistics showing scans
8. ✅ Test threat: "Ignore previous instructions"
9. ✅ Verify threat is blocked/logged

### Step 7: Update Strata Cloud Manager

1. **Log in to SCM**: https://identity.paloaltonetworks.com
2. **Navigate**: AI Security → Applications
3. **Find/Update**: `multi-agent-ai-assistant`
4. **Set Configuration**:
   ```
   Application Name: multi-agent-ai-assistant
   Application URL: [paste your NEW_URL from Step 5]
   Security Profile: Jerry_AI_Security_Profile ✓
   Deployment Profile: Jerry_AI_Demo ✓
   Framework: GCP Agent Builder
   Status: Active
   ```
5. **Click**: Save

### Step 8: Verify SCM Integration

**In your app:**
1. Run a few test queries
2. Note the session timestamp

**In SCM:**
1. Go to: AI Security → Monitoring
2. Filter by: `multi-agent-ai-assistant`
3. Look for recent events
4. Verify scan logs appear
5. Check threat detection is working

### Step 9: Delete Old Service (After Full Testing)

```bash
# Once you've confirmed everything works:

# Check what services you have
gcloud run services list --region asia-southeast1

# Delete the old service
gcloud run services delete streamlit-ai-demo \
    --region asia-southeast1 \
    --quiet

echo "✅ Old service deleted. Migration complete!"
```

---

## 🚀 Quick Deploy Script

Save this as `deploy_new_service.sh`:

```bash
#!/bin/bash
set -e

# Configuration
export GCP_PROJECT_ID="your-project-id"  # UPDATE THIS
GCP_REGION="asia-southeast1"
NEW_SERVICE="multi-agent-ai-assistant"
OLD_SERVICE="streamlit-ai-demo"

echo "🚀 Deploying ${NEW_SERVICE}..."

# Set project
gcloud config set project ${GCP_PROJECT_ID}

# Build image
echo "📦 Building Docker image..."
gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/${NEW_SERVICE}

# Deploy
echo "🌐 Deploying to Cloud Run..."
gcloud run deploy ${NEW_SERVICE} \
    --image gcr.io/${GCP_PROJECT_ID}/${NEW_SERVICE} \
    --platform managed \
    --region ${GCP_REGION} \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest"

# Get URL
NEW_URL=$(gcloud run services describe ${NEW_SERVICE} \
    --region ${GCP_REGION} \
    --format="value(status.url)")

echo ""
echo "✅ Deployment Complete!"
echo "🌐 New URL: ${NEW_URL}"
echo ""
echo "Next steps:"
echo "1. Test the new service at the URL above"
echo "2. Update SCM with the new URL"
echo "3. After testing, delete old service:"
echo "   gcloud run services delete ${OLD_SERVICE} --region ${GCP_REGION}"
```

**Run it:**
```bash
chmod +x deploy_new_service.sh
./deploy_new_service.sh
```

---

## 📊 Comparison: Before & After

| Aspect | Before | After |
|--------|--------|-------|
| **Service Name** | streamlit-ai-demo | multi-agent-ai-assistant ✅ |
| **URL** | streamlit-ai-demo-....run.app | multi-agent-ai-assistant-....run.app ✅ |
| **SCM App Name** | multi-agent-ai-assistant | multi-agent-ai-assistant ✅ |
| **Consistency** | ❌ Mismatch | ✅ All aligned |

---

## 🔍 Troubleshooting

### Issue: "Project not set"
```bash
export GCP_PROJECT_ID="your-project-id"
gcloud config set project ${GCP_PROJECT_ID}
```

### Issue: "Secrets not found"
```bash
# Create missing secrets
echo -n "key_value" | gcloud secrets create SECRET_NAME --data-file=-
```

### Issue: "Permission denied on secrets"
```bash
# Grant access
PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding AIRS_API_KEY \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"
```

### Issue: "Build failed"
```bash
# Check you're in project directory with Dockerfile
ls -la Dockerfile requirements.txt app.py

# Ensure APIs enabled
gcloud services enable cloudbuild.googleapis.com
```

### Issue: "Service not accessible"
```bash
# Check service status
gcloud run services describe multi-agent-ai-assistant \
    --region asia-southeast1

# Check logs
gcloud run logs read \
    --service multi-agent-ai-assistant \
    --region asia-southeast1 \
    --limit 50
```

---

## ✅ Final Checklist

After completing the rename:

- [ ] New service deployed: `multi-agent-ai-assistant`
- [ ] New URL obtained and tested
- [ ] App loads and works correctly
- [ ] Security agent initializes successfully
- [ ] All agents functional (weather, events, etc.)
- [ ] SCM updated with new URL
- [ ] SCM showing scan events
- [ ] Threat detection verified
- [ ] Old service deleted (after testing)
- [ ] Team notified of new URL

---

## 🎯 Summary

**What you're doing:**
- Creating a NEW Cloud Run service with the correct name
- Testing it thoroughly
- Updating SCM to point to the new URL
- Deleting the old service

**Why this approach:**
- ✅ Zero downtime
- ✅ Easy to rollback
- ✅ Test before switching
- ✅ Keep old service until confirmed

**Result:**
- Everything named consistently: `multi-agent-ai-assistant`
- Matches your SCM configuration
- Clean, professional setup

---

## 📞 Need Help?

**GCP Issues:**
```bash
# Check service logs
gcloud run logs read --service multi-agent-ai-assistant --region asia-southeast1

# Get service details
gcloud run services describe multi-agent-ai-assistant --region asia-southeast1
```

**SCM Issues:**
- Verify API key is valid
- Check security profile is active
- Ensure application URL is correct (include https://)

**App Issues:**
- Check environment variables/secrets are set
- Verify all agents are present
- Review application logs

---

**Good luck with the deployment! 🚀**
