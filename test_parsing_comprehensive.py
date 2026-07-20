#!/usr/bin/env python
"""Test the improved report parsing with simulated Gemini responses"""

import sys
import json
import os

# Ensure we're using the correct path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after path is set
from src.chatbot.bot import extract_report_sections, REPORT_SECTION_KEYS

def test_format(name, test_input):
    """Test a single format"""
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print('='*70)
    
    result = extract_report_sections(test_input)
    
    if result:
        print(f"✅ SUCCESS - Sections found: {len(result)}/{len(REPORT_SECTION_KEYS)}")
        for key in REPORT_SECTION_KEYS:
            if key in result:
                content = result[key][:50] + "..." if len(result[key]) > 50 else result[key]
                print(f"  ✓ {key}: {content}")
            else:
                print(f"  ✗ {key}: MISSING")
        return True
    else:
        print(f"❌ FAILED - No sections extracted")
        return False

# Test Case 1: Perfect JSON response from Gemini
test1_json = {
    "Clinical Interpretation": "Retinal examination reveals early-stage diabetic retinopathy with scattered microaneurysms visible in the temporal region.",
    "Disease Summary": "The retinal fundus shows signs consistent with mild diabetic retinopathy. Early intervention recommended.",
    "Possible Medical Concerns": "Progressive vision loss without intervention. Risk of severe retinopathy if blood glucose remains poorly controlled.",
    "Treatment Guidance": "Urgent consultation with ophthalmologist. Consider laser photocoagulation if lesions progress. Strict glycemic control essential.",
    "Lifestyle Recommendations": "Maintain blood glucose target <130 mg/dL. Regular eye screening every 3 months. Daily moderate exercise.",
    "Follow-up Advice": "Repeat retinal imaging in 3 months. Monitor symptoms closely. Immediate evaluation if sudden vision changes occur.",
    "Medical Disclaimer": "This assessment is preliminary. Clinical diagnosis requires professional ophthalmologic evaluation. Always consult specialists."
}

# Test Case 2: JSON wrapped in code blocks (with markdown fence)
test2_code = f"""```json
{json.dumps(test1_json, indent=2)}
```"""

# Test Case 3: Markdown with headers
test3_markdown = """## Clinical Interpretation
Retinal examination reveals early-stage diabetic retinopathy with scattered microaneurysms visible in the temporal region.

## Disease Summary  
The retinal fundus shows signs consistent with mild diabetic retinopathy. Early intervention recommended.

## Possible Medical Concerns
Progressive vision loss without intervention. Risk of severe retinopathy if blood glucose remains poorly controlled.

## Treatment Guidance
Urgent consultation with ophthalmologist. Consider laser photocoagulation if lesions progress. Strict glycemic control essential.

## Lifestyle Recommendations
Maintain blood glucose target <130 mg/dL. Regular eye screening every 3 months. Daily moderate exercise.

## Follow-up Advice
Repeat retinal imaging in 3 months. Monitor symptoms closely. Immediate evaluation if sudden vision changes occur.

## Medical Disclaimer
This assessment is preliminary. Clinical diagnosis requires professional ophthalmologic evaluation. Always consult specialists."""

# Test Case 4: With alternative headers (using dashes)
test4_dashes = """Clinical Interpretation:
Retinal examination reveals early-stage diabetic retinopathy with scattered microaneurysms visible in the temporal region.

Disease Summary:
The retinal fundus shows signs consistent with mild diabetic retinopathy. Early intervention recommended.

Possible Medical Concerns:
Progressive vision loss without intervention. Risk of severe retinopathy if blood glucose remains poorly controlled.

Treatment Guidance:
Urgent consultation with ophthalmologist. Consider laser photocoagulation if lesions progress. Strict glycemic control essential.

Lifestyle Recommendations:
Maintain blood glucose target <130 mg/dL. Regular eye screening every 3 months. Daily moderate exercise.

Follow-up Advice:
Repeat retinal imaging in 3 months. Monitor symptoms closely. Immediate evaluation if sudden vision changes occur.

Medical Disclaimer:
This assessment is preliminary. Clinical diagnosis requires professional ophthalmologic evaluation. Always consult specialists."""

# Test Case 5: Malformed JSON in code blocks (common Gemini response)
test5_malformed = """Here's the retinal analysis report:

```json
{
  "Clinical Interpretation": "Retinal findings show early diabetic changes",
  "Disease Summary": "Mild DR detected in the macula",
  "Possible Medical Concerns": "Vision loss risk if untreated",
  "Treatment Guidance": "Refer to ophthalmologist for monitoring",
  "Lifestyle Recommendations": "Control blood glucose levels",
  "Follow-up Advice": "Retinal screening in 6 months",
  "Medical Disclaimer": "Not a substitute for professional medical diagnosis"
}
```

Please follow up with your healthcare provider immediately."""

# Test Case 6: Mixed format (some headers, some plain text)
test6_mixed = """**Clinical Interpretation**: Early retinal changes consistent with type 2 diabetes

- Disease Summary: Patient shows microaneurysms in peripheral retina
* Possible Medical Concerns: Progressive vision loss without treatment
- Treatment Guidance: Ophthalmologist consultation recommended

Lifestyle Recommendations
Control your blood sugar through diet and exercise.

Follow-up Advice: Schedule retinal imaging every 3-6 months

Medical Disclaimer: Seek professional medical advice."""

# Test Case 7: Plain text without clear structure (fallback scenario)
test7_plain = """The retinal imaging analysis shows signs of early diabetic retinopathy with scattered microaneurysms in the peripheral retina. This is a concerning finding that requires immediate attention from an ophthalmologist. The patient should maintain strict blood glucose control through diet, medication, and lifestyle modifications. Regular monitoring with retinal imaging is essential to track disease progression. A follow-up examination should be scheduled within 3-6 months. Please note that this analysis is for informational purposes only and should not replace professional medical evaluation and diagnosis. The patient is advised to consult with a qualified eye specialist for comprehensive assessment and management."""

# Run all tests
results = []
results.append(test_format("Test 1: Direct JSON", json.dumps(test1_json)))
results.append(test_format("Test 2: JSON in Code Blocks", test2_code))
results.append(test_format("Test 3: Markdown Headers", test3_markdown))
results.append(test_format("Test 4: Colon-Separated", test4_dashes))
results.append(test_format("Test 5: Malformed JSON in Code Blocks", test5_malformed))
results.append(test_format("Test 6: Mixed Format", test6_mixed))
results.append(test_format("Test 7: Plain Text Fallback", test7_plain))

# Summary
print(f"\n\n{'='*70}")
print("TEST SUMMARY")
print('='*70)
passed = sum(results)
total = len(results)
print(f"Passed: {passed}/{total}")
if passed == total:
    print("✅ All tests PASSED!")
else:
    print(f"⚠️  {total - passed} tests failed")
print('='*70)
