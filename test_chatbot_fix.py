#!/usr/bin/env python3
"""
Chatbot Diagnostic Test Script
Demonstrates the new chatbot fixes and diagnostic output
"""

import sys
sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

from src.chatbot.bot import chatbot_response, validate_api_key
from dotenv import load_dotenv
import os

print("\n" + "=" * 80)
print("CHATBOT DIAGNOSTIC TEST")
print("=" * 80)

load_dotenv()

# Test 1: API Key Validation
print("\n[TEST 1] API Key Validation")
print("-" * 80)

is_valid, msg = validate_api_key()
print(f"Status: {msg}")
print(f"Valid: {is_valid}")

if not is_valid:
    print("\n⚠️  CRITICAL: API Key is invalid!")
    print("\nFIX REQUIRED:")
    print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create or select your project")
    print("3. Enable 'Generative Language API' (not Vertex AI)")
    print("4. Create an API key (not OAuth)")
    print("5. Copy the key (should start with 'AIza')")
    print("6. Update .env file: GEMINI_API_KEY=your_api_key")
    print("7. Current key starts with:", os.getenv("GEMINI_API_KEY", "NOT_SET")[:10] if os.getenv("GEMINI_API_KEY") else "NOT_SET")
    sys.exit(1)

# Test 2: Test Message
print("\n[TEST 2] Testing Chatbot Response")
print("-" * 80)
print("Sending test message: 'What is diabetes?'")
print("-" * 80)

response = chatbot_response("What is diabetes?")

print("\n" + "=" * 80)
print("FINAL RESPONSE:")
print("=" * 80)
print(response)
print("=" * 80)

print("\n✓ Test completed successfully!")
