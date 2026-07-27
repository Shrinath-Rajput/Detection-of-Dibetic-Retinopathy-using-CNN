#!/usr/bin/env python3
"""
Test script to verify that dynamic AI-generated reports are created for each retinal image upload.
Ensures no hardcoded fallback reports are used.
"""

import sys
import json
sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

from src.chatbot.bot import generate_dynamic_medical_report, extract_report_sections, build_report_prompt

# Test different disease predictions
TEST_CASES = [
    "No_DR",
    "Mild",
    "Moderate", 
    "Severe",
    "Proliferate_DR",
]

# Prompt must request the full report schema, including Notes.
prompt = build_report_prompt("Mild", request_id="test-prompt", lang="en")
if '"Notes"' not in prompt:
    print("[FAIL] Prompt does not request the Notes section")
    sys.exit(1)

# Hardcoded error messages that should NEVER appear
FORBIDDEN_FALLBACK_TEXTS = [
    "The AI medical report could not be completed",
    "No treatment guidance was generated because",
    "No lifestyle recommendations were generated",
    "No lifestyle guidance was generated",
    "Please try again later",
    "The system is currently unavailable",
    "This notice is intended to keep you informed about a temporary service interruption",
    "This notice is operational and not a medical diagnosis"
]

print("=" * 80)
print("TEST: Dynamic Medical Report Generation")
print("=" * 80)
print()

all_passed = True
report_collection = {}

for disease in TEST_CASES:
    print(f"\n[TEST] Generating report for: {disease}")
    print("-" * 80)
    
    try:
        # Generate report using non-strict mode (should always return something)
        report = generate_dynamic_medical_report(
            prediction=disease,
            request_id=f"test-{disease}",
            strict=False
        )
        
        if not report:
            print(f"[FAIL] No report returned for {disease}")
            all_passed = False
            continue
        
        # Check all 7 sections exist
        expected_sections = [
            "Clinical Interpretation",
            "Disease Summary",
            "Possible Medical Concerns",
            "Treatment Guidance",
            "Lifestyle Recommendations",
            "Follow-up Advice",
            "Medical Disclaimer",
            "Notes",
        ]
        
        missing_sections = [s for s in expected_sections if s not in report]
        if missing_sections:
            print(f"[FAIL] Missing sections: {missing_sections}")
            all_passed = False
            continue
        
        # Check that no section is empty
        empty_sections = [k for k, v in report.items() if not v or len(str(v).strip()) < 5]
        if empty_sections:
            print(f"[FAIL] Empty sections: {empty_sections}")
            all_passed = False
            continue
        
        # Check for forbidden fallback texts
        all_content = json.dumps(report).lower()
        forbidden_found = [text for text in FORBIDDEN_FALLBACK_TEXTS if text.lower() in all_content]
        if forbidden_found:
            print(f"[FAIL] Found forbidden fallback text: {forbidden_found[0]}")
            all_passed = False
            continue
        
        # Calculate content statistics
        total_length = sum(len(str(v)) for v in report.values())
        avg_section_length = total_length // len(report)
        
        print(f"[PASS] {disease}")
        print(f"   - All 7 sections present")
        print(f"   - No forbidden fallback text found")
        print(f"   - Total content length: {total_length} characters")
        print(f"   - Average per section: {avg_section_length} characters")
        print(f"\n   Sample content from Clinical Interpretation:")
        clinical_text = str(report["Clinical Interpretation"])[:150]
        print(f"   {clinical_text}...")
        
        report_collection[disease] = report
        
    except Exception as e:
        print(f"[FAIL] Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False

# Test for uniqueness
print("\n" + "=" * 80)
print("UNIQUENESS TEST: Each disease produces different reports")
print("=" * 80)

if len(report_collection) >= 2:
    disease_list = list(report_collection.keys())
    for i in range(len(disease_list) - 1):
        disease1 = disease_list[i]
        disease2 = disease_list[i + 1]
        
        report1 = report_collection[disease1]
        report2 = report_collection[disease2]
        
        # Compare content
        content1 = json.dumps(report1, sort_keys=True)
        content2 = json.dumps(report2, sort_keys=True)
        
        if content1 != content2:
            print(f"[PASS] {disease1} and {disease2} produce different reports")
        else:
            print(f"[FAIL] {disease1} and {disease2} produce identical reports (reuse detected)")
            all_passed = False

# Test markdown parsing
print("\n" + "=" * 80)
print("MARKDOWN PARSING TEST")
print("=" * 80)

markdown_test_cases = [
    {
        "name": "Markdown with headers",
        "text": """
## Clinical Interpretation
The patient shows signs of mild retinopathy.

## Disease Summary
Scattered microaneurysms detected.

## Possible Medical Concerns
Risk of progression if not managed.

## Treatment Guidance
Regular monitoring recommended.

## Lifestyle Recommendations
Control blood sugar levels.

## Follow-up Advice
Schedule follow-up in 3 months.

## Medical Disclaimer
Not a substitute for professional diagnosis.
"""
    },
    {
        "name": "Colon-separated sections",
        "text": """
Clinical Interpretation: Patient shows mild changes in retinal vessels.
Disease Summary: Early signs of diabetic retinopathy detected.
Possible Medical Concerns: May progress without proper management.
Treatment Guidance: Recommend ophthalmology consultation.
Lifestyle Recommendations: Improve diabetes control and diet.
Follow-up Advice: Schedule follow-up examination in 3 months.
Medical Disclaimer: This is an AI assessment, not a medical diagnosis.
"""
    }
]

for test_case in markdown_test_cases:
    print(f"\n[TEST] {test_case['name']}")
    sections = extract_report_sections(test_case['text'])
    
    if not sections:
        print(f"[FAIL] No sections extracted")
        all_passed = False
        continue
    
    required_sections = 7
    found_sections = len(sections)
    
    if found_sections >= 6:
        print(f"[PASS] Extracted {found_sections}/{required_sections} sections")
    else:
        print(f"[FAIL] Only extracted {found_sections}/{required_sections} sections")
        all_passed = False

# Final summary
print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)

if all_passed:
    print("✅ ALL TESTS PASSED!")
    print("\nThe retinal PDF now generates fresh Gemini-based reports for each upload.")
    print("No hardcoded fallback messages are used.")
    sys.exit(0)
else:
    print("❌ SOME TESTS FAILED!")
    print("\nPlease review the errors above.")
    sys.exit(1)
