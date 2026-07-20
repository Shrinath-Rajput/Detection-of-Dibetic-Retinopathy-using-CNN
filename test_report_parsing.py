#!/usr/bin/env python
"""Test script to verify the improved report parsing logic"""

import sys
import json
sys.path.insert(0, 'd:/e drive/Only_Project/dr_cnn')

from src.chatbot.bot import extract_report_sections, REPORT_SECTION_KEYS

# Test Case 1: Valid JSON format
test_json = {
    "Clinical Interpretation": "Retinal findings consistent with mild diabetic retinopathy.",
    "Disease Summary": "Early-stage diabetes-related changes detected.",
    "Possible Medical Concerns": "Progressive vision loss risk if untreated.",
    "Treatment Guidance": "Consult ophthalmologist for management.",
    "Lifestyle Recommendations": "Blood glucose monitoring essential.",
    "Follow-up Advice": "Recheck in 3-6 months.",
    "Medical Disclaimer": "This is preliminary assessment only."
}

test_json_str = json.dumps(test_json)
print("=" * 60)
print("Test 1: Direct JSON")
print("=" * 60)
result = extract_report_sections(test_json_str)
print(f"Result: {result is not None}")
if result:
    print(f"Sections found: {len(result)}")
    for key in REPORT_SECTION_KEYS:
        if key in result:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key}")

# Test Case 2: JSON in code blocks
test_json_codeblock = f"""```json
{json.dumps(test_json, indent=2)}
```"""

print("\n" + "=" * 60)
print("Test 2: JSON in Code Blocks")
print("=" * 60)
result = extract_report_sections(test_json_codeblock)
print(f"Result: {result is not None}")
if result:
    print(f"Sections found: {len(result)}")
    for key in REPORT_SECTION_KEYS:
        if key in result:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key}")

# Test Case 3: Markdown format with headers
test_markdown = """
## Clinical Interpretation
Retinal findings consistent with mild diabetic retinopathy.

## Disease Summary
Early-stage diabetes-related changes detected.

## Possible Medical Concerns
Progressive vision loss risk if untreated.

## Treatment Guidance
Consult ophthalmologist for management.

## Lifestyle Recommendations
Blood glucose monitoring essential.

## Follow-up Advice
Recheck in 3-6 months.

## Medical Disclaimer
This is preliminary assessment only.
"""

print("\n" + "=" * 60)
print("Test 3: Markdown Headers")
print("=" * 60)
result = extract_report_sections(test_markdown)
print(f"Result: {result is not None}")
if result:
    print(f"Sections found: {len(result)}")
    for key in REPORT_SECTION_KEYS:
        if key in result:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key}")

# Test Case 4: Colon-separated format
test_colon = """
Clinical Interpretation: Retinal findings consistent with mild diabetic retinopathy.

Disease Summary: Early-stage diabetes-related changes detected.

Possible Medical Concerns: Progressive vision loss risk if untreated.

Treatment Guidance: Consult ophthalmologist for management.

Lifestyle Recommendations: Blood glucose monitoring essential.

Follow-up Advice: Recheck in 3-6 months.

Medical Disclaimer: This is preliminary assessment only.
"""

print("\n" + "=" * 60)
print("Test 4: Colon-Separated Format")
print("=" * 60)
result = extract_report_sections(test_colon)
print(f"Result: {result is not None}")
if result:
    print(f"Sections found: {len(result)}")
    for key in REPORT_SECTION_KEYS:
        if key in result:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key}")

# Test Case 5: Mixed plain text with some structure
test_plain = """
The imaging assessment shows mild diabetic changes. Early detection allows for better management. 

Key concerns include potential vision degradation. Patients should maintain blood glucose control through diet and medication. Follow-up imaging recommended in 3-6 months. This assessment is not a substitute for professional medical consultation.

Additional clinical notes: The retina shows some microaneurysms but no significant hemorrhages yet.
"""

print("\n" + "=" * 60)
print("Test 5: Plain Text (Fallback Test)")
print("=" * 60)
result = extract_report_sections(test_plain)
print(f"Result: {result is not None}")
if result:
    print(f"Sections found: {len(result)}")
    for key in REPORT_SECTION_KEYS:
        if key in result:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key}")

print("\n" + "=" * 60)
print("Testing Summary: All test cases completed")
print("=" * 60)
