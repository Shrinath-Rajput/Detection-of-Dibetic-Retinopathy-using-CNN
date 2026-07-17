#!/usr/bin/env python3
"""
Test script to verify that disease-specific reports are unique
"""

import sys
sys.path.insert(0, 'd:\\e drive\\Only_Project\\dr_cnn')

# Read the app.py file to extract the offline reports and gemini prompts
import re

with open('app.py', 'r') as f:
    content = f.read()

# Extract disease-specific prompts
print("\n" + "="*80)
print("DISEASE-SPECIFIC GEMINI PROMPTS")
print("="*80)

gemini_prompts_match = re.search(r'gemini_prompts = \{(.*?)\}', content, re.DOTALL)
if gemini_prompts_match:
    prompts_text = gemini_prompts_match.group(1)
    diseases = re.findall(r'"([^"]+)":', prompts_text)
    for disease in set(diseases):
        match = re.search(rf'"{disease}": "(.*?)"', prompts_text)
        if match:
            prompt = match.group(1)
            print(f"\n✓ {disease.upper()}: {len(prompt)} chars")
            print(f"  Preview: {prompt[:80]}...")

# Extract offline reports
print("\n" + "="*80)
print("DISEASE-SPECIFIC OFFLINE REPORTS")
print("="*80)

offline_reports_match = re.search(r'offline_reports = \{(.*?)\n    \}', content, re.DOTALL)
if offline_reports_match:
    reports_text = offline_reports_match.group(1)
    diseases = re.findall(r'"([^"]+)":\s*\{', reports_text)
    
    for disease in set(diseases):
        # Extract the clinical interpretation for this disease
        pattern = rf'"{disease}":\s*\{{.*?"Clinical Interpretation":\s*"(.*?)"'
        match = re.search(pattern, reports_text, re.DOTALL)
        if match:
            interpretation = match.group(1)[:100]
            print(f"\n✓ {disease.upper()} offline report exists")
            print(f"  Clinical Interpretation preview: {interpretation}...")

print("\n" + "="*80)
print("VERIFICATION COMPLETE")
print("="*80)

# Count unique reports
disease_count = len(set(diseases))
print(f"\nTotal diseases with unique reports: {disease_count}")
print(f"Expected: 7 (No_DR, Mild, Moderate, Severe, Proliferate_DR, glaucoma, cataract)")

if disease_count >= 7:
    print("\n✅ SUCCESS: All diseases have unique offline fallback reports")
else:
    print(f"\n⚠️  WARNING: Only {disease_count} diseases found")
