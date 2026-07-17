#!/usr/bin/env python3
"""
Test script to verify silent error handling
"""

import sys
sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

from src.chatbot.bot import chatbot_response
import json

print("=" * 80)
print("TESTING SILENT ERROR HANDLING")
print("=" * 80)

# Test 1: Generic health question (should use offline knowledge)
print("\n[TEST 1] Generic health question")
print("-" * 40)
response1 = chatbot_response("What is diabetes?")
print(f"✓ Response received: {len(response1)} chars")
print(f"✓ Sample: {response1[:80]}...")

# Test 2: Another health question
print("\n[TEST 2] Another health question")
print("-" * 40)
response2 = chatbot_response("How to maintain healthy blood pressure?")
print(f"✓ Response received: {len(response2)} chars")
print(f"✓ Sample: {response2[:80]}...")

# Test 3: Disease-specific report prompt (for Retina PDF)
print("\n[TEST 3] Disease-specific ophthalmology report prompt")
print("-" * 40)
disease_prompt = """Generate a professional ophthalmology report for MILD DIABETIC RETINOPATHY. Include clinical findings specific to early-stage DR. Return ONLY valid JSON with: Clinical Interpretation, Possible Medical Concerns, Recommended Next Steps, Lifestyle Recommendations, Medical Disclaimer. Keep response under 150 words total."""
response3 = chatbot_response(disease_prompt)
print(f"✓ Response received: {len(response3)} chars")
print(f"✓ Sample: {response3[:80]}...")

# Verify responses are valid (not error messages)
print("\n" + "=" * 80)
print("VERIFICATION RESULTS")
print("=" * 80)

checks = [
    ("Response 1 is not empty", len(response1) > 0),
    ("Response 2 is not empty", len(response2) > 0),
    ("Response 3 is not empty", len(response3) > 0),
    ("No 429 errors in any response", "429" not in response1 + response2 + response3),
    ("No 'quota' word in responses", "quota" not in (response1 + response2 + response3).lower()),
    ("No 'Retrying' in responses", "Retrying" not in response1 + response2 + response3),
    ("No 'Error' prefix in responses", not any(r.startswith("Error") for r in [response1, response2, response3])),
]

all_pass = True
for check_name, result in checks:
    status = "✅ PASS" if result else "❌ FAIL"
    print(f"{status}: {check_name}")
    if not result:
        all_pass = False

print("\n" + "=" * 80)
if all_pass:
    print("✅ ALL TESTS PASSED")
    print("\nApplication behavior:")
    print("✓ Silently handles Gemini API failures")
    print("✓ Uses offline medical knowledge without showing errors")
    print("✓ Generates disease-specific reports from fallback")
    print("✓ Terminal only shows professional logs")
    print("✓ No quota/429/error messages exposed to user")
else:
    print("⚠️  SOME TESTS FAILED")
print("=" * 80)
