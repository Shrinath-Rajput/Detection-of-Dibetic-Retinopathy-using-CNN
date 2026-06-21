#!/usr/bin/env python3
"""
Standalone Gemini API diagnostic script
Tests API key quota and billing status
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv

print("\n" + "=" * 80)
print("GEMINI API DIAGNOSTIC TEST")
print("=" * 80)

# Load environment variables
load_dotenv()
gemini_key = os.getenv("GEMINI_API_KEY")

print("\n[1] API Key Status")
print("-" * 80)
if gemini_key:
    print(f"✓ GEMINI_API_KEY is loaded from .env")
    print(f"  First 10 chars: {gemini_key[:10]}")
    print(f"  Last 10 chars:  {gemini_key[-10:]}")
    print(f"  Total length:   {len(gemini_key)}")
else:
    print("✗ GEMINI_API_KEY NOT FOUND in .env")
    sys.exit(1)

# Test API endpoints
print("\n[2] Testing Gemini API Endpoints")
print("-" * 80)

api_endpoints = [
    ("gemini-2.0-flash", "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent"),
    ("gemini-1.5-flash-latest", "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"),
    ("gemini-1.5-pro-latest", "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent"),
]

test_payload = {
    "contents": [
        {
            "parts": [
                {
                    "text": "Hello, what is 2+2?"
                }
            ]
        }
    ]
}

for model_name, api_url in api_endpoints:
    print(f"\nTesting: {model_name}")
    print(f"URL: {api_url}")
    
    try:
        response = requests.post(
            f"{api_url}?key={gemini_key}",
            headers={"Content-Type": "application/json"},
            json=test_payload,
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        
        # Try to parse response
        try:
            response_json = response.json()
            print(f"Response: {json.dumps(response_json, indent=2)}")
        except:
            print(f"Response: {response.text}")
        
        # Check for specific error messages
        response_text = response.text.lower()
        if "quota" in response_text:
            print("⚠️  QUOTA ISSUE DETECTED")
        elif "billing" in response_text:
            print("⚠️  BILLING ISSUE DETECTED")
        elif "not found" in response_text or "404" in str(response.status_code):
            print("⚠️  MODEL NOT FOUND OR API NOT ENABLED")
        elif response.status_code == 200:
            print("✓ SUCCESS - API KEY AND QUOTA OK")
            break
            
    except Exception as e:
        print(f"Error: {str(e)}")

# Test direct API call like chatbot does
print("\n[3] Testing Chatbot Payload Format")
print("-" * 80)

url = "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent"
payload = {
    "contents": [
        {
            "parts": [
                {
                    "text": "You are a helpful AI. Answer: What is diabetes?"
                }
            ]
        }
    ]
}

print(f"URL: {url}")
print(f"Payload: {json.dumps(payload, indent=2)}")

try:
    response = requests.post(
        f"{url}?key={gemini_key}",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=10
    )
    
    print(f"\nStatus: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print(f"\nFull Response:")
    try:
        print(json.dumps(response.json(), indent=2))
    except:
        print(response.text)
        
except Exception as e:
    print(f"Error: {str(e)}")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80 + "\n")

print("\nCommon Issues:")
print("-" * 80)
print("1. Quota Exceeded (429):")
print("   - API doesn't have quota remaining")
print("   - Check Google Cloud Console > Gemini API > Quotas")
print("   - Enable billing for the project")
print("   - Request quota increase if needed")
print()
print("2. API Not Enabled (404):")
print("   - Go to Google Cloud Console")
print("   - Enable 'Generative Language API'")
print("   - Wait 1-2 minutes for activation")
print()
print("3. Authentication Error (401):")
print("   - Check if API key is correct")
print("   - Verify key has API Generative Language API enabled")
print("   - Regenerate key if corrupted")
print()
print("4. Billing Not Set Up:")
print("   - Add payment method to Google Cloud account")
print("   - Billing must be enabled for Gemini API")
print()
