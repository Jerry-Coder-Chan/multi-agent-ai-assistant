# Quick Reference - AIRS Integration & GCP Rename

## 📋 Your Configuration

```yaml
Strata Cloud Manager:
  Application: multi-agent-ai-assistant
  Security Profile: Jerry_AI_Security_Profile ✓
  Deployment Profile: Jerry_AI_Demo ✓
  Framework: GCP Agent Builder
  API Key: AIRS_API_Key

GCP Cloud Run:
  Service: multi-agent-ai-assistant
  Region: asia-southeast1
  
File Naming:
  ✅ security_agent.py (lowercase with underscore)
```

---

## 🚀 Quick Deploy Commands

### 1. Set Your Project
```bash
export GCP_PROJECT_ID="your-project-id"
gcloud config set project ${GCP_PROJECT_ID}
```

### 2. Create Secrets (if not exists)
```bash
# Check first
gcloud secrets list

# Create if missing
echo -n "your_openai_key" | gcloud secrets create OPENAI_API_KEY --data-file=-
echo -n "your_weather_key" | gcloud secrets create WEATHER_API_KEY --data-file=-
echo -n "your_airs_key" | gcloud secrets create AIRS_API_KEY --data-file=-
echo -n "your_serpapi_key" | gcloud secrets create SERPAPI_API_KEY --data-file=-  # optional
echo -n "your_qwen_key" | gcloud secrets create DASHSCOPE_API_KEY --data-file=-    # optional

# Grant access
PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in OPENAI_API_KEY WEATHER_API_KEY AIRS_API_KEY SERPAPI_API_KEY DASHSCOPE_API_KEY; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 3. Deploy New Service
```bash
# Build
gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant

# Deploy
gcloud run deploy multi-agent-ai-assistant \
    --image gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant \
    --platform managed \
    --region asia-southeast1 \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest,SERPAPI_API_KEY=SERPAPI_API_KEY:latest,DASHSCOPE_API_KEY=DASHSCOPE_API_KEY:latest" \
    --set-env-vars="DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1,OLLAMA_BASE_URL=http://localhost:11434,OLLAMA_MODEL=llama3.2,OLLAMA_TIMEOUT=120"
```

### 4. Get URL
```bash
gcloud run services describe multi-agent-ai-assistant \
    --region asia-southeast1 \
    --format="value(status.url)"
```

### 5. Delete Old Service (after testing)
```bash
gcloud run services delete streamlit-ai-demo \
    --region asia-southeast1 \
    --quiet
```

---

## 📁 File Placement

```
your-project/
├── agents/
│   ├── security_agent.py      ← Use this (lowercase!)
│   ├── controller_agent.py     ← Replace
│   ├── chat_agent.py
│   ├── weather_agent.py
│   ├── event_agent.py
│   ├── recommendation_agent.py
│   ├── rag_agent.py
│   └── image_agent.py
├── app.py                      ← Replace
├── requirements.txt            ← Replace
├── Dockerfile
└── data/
```

---

## ✅ Testing Checklist

### In Your App:
```
1. Visit new URL
2. Enter API keys in sidebar
3. Initialize assistant
4. Check for: "🔒 AIRS connection healthy"
5. Security Settings visible:
   ✅ Scan User Prompts
   ✅ Scan AI Responses  
   ✅ Block Threats
6. Run test: "What events are today?"
7. Check Security Statistics
8. Test threat: "Ignore previous instructions"
9. Verify threat blocked
```

### In SCM:
```
1. Go to AI Security → Applications
2. Update multi-agent-ai-assistant:
   - Application URL: [new URL]
   - Security Profile: Jerry_AI_Security_Profile
   - Deployment Profile: Jerry_AI_Demo
3. Save
4. Go to Monitoring
5. Filter by: multi-agent-ai-assistant
6. Verify scan events appear
```

---

## 🔍 Useful Commands

### Check Services
```bash
# List all services
gcloud run services list --region asia-southeast1

# Describe service
gcloud run services describe multi-agent-ai-assistant --region asia-southeast1

# Check logs
gcloud run logs read --service multi-agent-ai-assistant --region asia-southeast1 --limit 50
```

### Check Secrets
```bash
# List secrets
gcloud secrets list

# View secret metadata
gcloud secrets describe AIRS_API_KEY
gcloud secrets describe DASHSCOPE_API_KEY

# Access secret value (for testing)
gcloud secrets versions access latest --secret="AIRS_API_KEY"
```

### Check IAM
```bash
# View secret permissions
gcloud secrets get-iam-policy AIRS_API_KEY

# View project IAM
gcloud projects get-iam-policy ${GCP_PROJECT_ID}
```

---

## 🐛 Troubleshooting

### Service won't start
```bash
# Check logs
gcloud run logs read --service multi-agent-ai-assistant --region asia-southeast1 --limit 100 | grep ERROR

# Check environment
gcloud run services describe multi-agent-ai-assistant --region asia-southeast1 --format="yaml(spec.template.spec.containers[0])"
```

### Secrets not accessible
```bash
# Re-grant permissions
PROJECT_NUMBER=$(gcloud projects describe ${GCP_PROJECT_ID} --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding AIRS_API_KEY \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"
```

### AIRS not connecting
```bash
# Test API directly
curl -X POST \
  https://service.api.aisecurity.paloaltonetworks.com/v1/scan/sync/request \
  -H "Content-Type: application/json" \
  -H "x-pan-token: YOUR_AIRS_KEY" \
  -d '{
    "metadata": {
      "ai_model": "test",
      "app_name": "multi-agent-ai-assistant",
      "app_user": "test"
    },
    "contents": [{"prompt": "test", "response": "test"}],
    "tr_id": "test123",
    "ai_profile": {"profile_name": "Jerry_AI_Demo"}
  }'
```

---

## 📊 Service Comparison

| Aspect | Old | New |
|--------|-----|-----|
| **Service Name** | streamlit-ai-demo | multi-agent-ai-assistant |
| **URL** | streamlit-ai-demo-....run.app | multi-agent-ai-assistant-....run.app |
| **SCM App** | multi-agent-ai-assistant | multi-agent-ai-assistant |
| **Match** | ❌ | ✅ |

---

## 📚 Documentation Files

1. **RENAME_SERVICE_GUIDE.md** - Complete renaming guide
2. **SETUP_CHECKLIST.md** - Step-by-step setup
3. **GCP_SECRETS_GUIDE.md** - Secrets management
4. **AIRS_SETUP_GUIDE.md** - AIRS configuration
5. **README.md** - Project overview

---

## 🎯 Success Criteria

✅ New service deployed: `multi-agent-ai-assistant`
✅ App accessible via new URL
✅ All API keys working
✅ Security agent initialized
✅ AIRS scanning active
✅ Threats detected and blocked
✅ SCM showing events
✅ Statistics visible in app
✅ Old service deleted
✅ Everything aligned and consistent

---

## 💡 Pro Tips

1. **Test thoroughly** before deleting old service
2. **Keep old URL** handy for rollback if needed
3. **Monitor logs** during first few hours
4. **Check SCM** regularly for security insights
5. **Rotate secrets** every 90 days
6. **Update documentation** with new URL
7. **Notify team** of service name change

---

## ⚡ One-Line Deploy

```bash
export GCP_PROJECT_ID="your-id" && gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant && gcloud run deploy multi-agent-ai-assistant --image gcr.io/${GCP_PROJECT_ID}/multi-agent-ai-assistant --region asia-southeast1 --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,WEATHER_API_KEY=WEATHER_API_KEY:latest,AIRS_API_KEY=AIRS_API_KEY:latest,SERPAPI_API_KEY=SERPAPI_API_KEY:latest,DASHSCOPE_API_KEY=DASHSCOPE_API_KEY:latest" --set-env-vars="DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1,OLLAMA_BASE_URL=http://localhost:11434,OLLAMA_MODEL=llama3.2,OLLAMA_TIMEOUT=120"
```

---

**Last Updated**: February 2026  
**Status**: Ready for deployment 🚀
