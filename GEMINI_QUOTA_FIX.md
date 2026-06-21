# Gemini API Quota Diagnostic Guide

## Issue
HTTP 429 RESOURCE_EXHAUSTED - Quota exceeded for model gemini-2.0-flash

## Solution Steps

### Step 1: Run Diagnostic Script
```bash
cd d:\e drive\Only_Project\dr_cnn
python test_gemini_quota.py
```

This will:
- Verify API key is loaded from .env
- Show first 10 chars of loaded key
- Test multiple API endpoints
- Display full response from Gemini
- Identify specific error (quota, billing, API not enabled)

### Step 2: Interpret Results

**If you see HTTP 429:**
```
⚠️  QUOTA ISSUE DETECTED
- API key has no quota remaining
- Solution: See steps below
```

**If you see HTTP 404:**
```
⚠️  MODEL NOT FOUND OR API NOT ENABLED
- Generative Language API not enabled
- Solution: Enable API in Google Cloud Console
```

**If you see HTTP 401 or 403:**
```
⚠️  AUTHENTICATION/PERMISSION ISSUE
- API key is invalid or corrupted
- Solution: Regenerate API key
```

**If you see HTTP 200:**
```
✓ SUCCESS - API KEY AND QUOTA OK
- Everything is working
- Check chatbot logs for other issues
```

### Step 3: Fix Quota Issue (429)

**Option A: Check Current Quota**
1. Go to https://console.cloud.google.com
2. Select your project
3. Go to "APIs & Services" → "Generative Language API"
4. Click "Quotas" tab
5. Look for "requests_per_minute" or similar
6. If limit is 0 or exhausted, request quota increase

**Option B: Enable Billing**
1. Go to https://console.cloud.google.com
2. Go to "Billing" section
3. Click "Enable billing"
4. Add a payment method
5. Wait 1-2 minutes for activation
6. Try again

**Option C: Use Different API Key**
1. Go to Google Cloud Console
2. Go to "APIs & Services" → "Credentials"
3. Create a new API key
4. Update .env file:
   ```
   GEMINI_API_KEY=your_new_key_here
   ```
5. Restart app: `python app.py`

**Option D: Request Quota Increase**
1. In Google Cloud Console
2. Go to "APIs & Services" → "Quotas"
3. Find "Generative Language API"
4. Click "All quotas"
5. Select quota with limit 0
6. Click "Edit Quotas" at top
7. Request higher limit
8. Wait for Google to approve (usually instant)

### Step 4: Verify Fix

After fixing, run chatbot test:

**Terminal 1: Start Flask**
```bash
python app.py
```

**Terminal 2: Send test message**
```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is diabetes?"}'
```

**Check Terminal 1 output for:**
```
[GEMINI API DIAGNOSTIC]
============================================================
Loaded API Key (first 10)  : AQ.Ab8RN6I4g  (should match .env)
Loaded API Key (last 10)   : xxmlFW3Bp0j
API Key Length             : 56
API Key Source             : .env file (GEMINI_API_KEY)

[GEMINI API CALL]
============================================================
API URL         : https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent
Request Method  : POST
User Message    : What is diabetes?

Status Code     : 200
Response Headers: {...}

Full Response Body:
────────────────────────────────────────────────────────────
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "text": "Diabetes is a chronic condition..."
          }
        ]
      }
    }
  ]
}

[SUCCESS] Received response from Gemini
```

If Status Code is 200, ✓ **FIXED!**

### Step 5: Troubleshooting

**If still getting 429:**
- Quota was already exhausted
- Need to wait for quota reset (daily/monthly depending on plan)
- Or request higher quota in Console

**If still getting 404:**
- Enable "Generative Language API" in Google Cloud Console
- Wait 1-2 minutes
- Try again

**If wrong key is being loaded:**
- Verify .env file path: `d:\e drive\Only_Project\dr_cnn\.env`
- Check key format: Should be `AQ.Ab8RN...`
- Restart Flask app after changing .env

### Step 6: What Was Changed

**Files Modified:**
1. `src/chatbot/bot.py` - Enhanced diagnostics
2. `test_gemini_quota.py` - New diagnostic script

**Files NOT Changed:**
- `app.py` (routes untouched)
- All prediction models (DR, PCOD, diabetes, migraine)
- Frontend templates and CSS
- Sensor module
- Database connections

### Important Notes

- API key in .env is masked in logs (first/last 10 chars only)
- Full response body is printed for diagnosis
- Chatbot returns user-friendly error messages to frontend
- No personal data is exposed in logs
- Diagnostic info is server-side only (terminal output)

### Contact Support

If issue persists after all steps:
1. Check project has Generative Language API enabled
2. Verify billing is set up with payment method
3. Check API key wasn't regenerated elsewhere
4. Ensure no third-party API key usage (no OpenAI key mixed up)
5. Try creating completely new API key
