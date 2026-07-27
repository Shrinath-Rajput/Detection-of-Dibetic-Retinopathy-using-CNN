import sys

sys.path.insert(0, 'd:/e drive/Only_Project/dr_cnn')

from src.chatbot.bot import extract_report_sections, REPORT_SECTION_KEYS


def test_extract_report_sections_supports_section_numbered_headers():
    text = """
    Expert Ophthalmologist report.

    Section 1: Clinical Interpretation
    The retinal fundus shows no evidence of diabetic retinopathy in either eye.
    The vessels appear normal and there is no macular edema.

    Section 2: Disease Summary
    The current imaging does not show diabetic retinopathy or other acute retinal damage.
    Ongoing metabolic control remains important for long-term eye health.

    Section 3: Possible Medical Concerns
    Persistent high glucose levels may increase the risk of future retinal complications.
    Blood pressure and cholesterol should be monitored closely.

    Section 4: Treatment Guidance
    Continue routine diabetes management and schedule regular ophthalmic follow-up.
    Seek prompt care if new visual symptoms appear.

    Section 5: Lifestyle Recommendations
    Maintain a balanced diet, regular exercise, and good hydration habits.
    Avoid smoking and follow your clinician's recommendations.

    Section 6: Follow-up Advice
    Repeat screening at the recommended interval and report any visual changes immediately.
    Keep all follow-up appointments to monitor eye health.

    Section 7: Medical Disclaimer
    This report is informational and should be reviewed with a qualified healthcare provider.
    It does not replace a full clinical examination.

    Section 8: Notes
    Long-term blood sugar control is essential to reduce future retinal risk.
    Keep records of symptoms and follow-up care.
    """

    sections = extract_report_sections(text)

    assert sections is not None
    assert len(sections) >= len(REPORT_SECTION_KEYS) - 1
    for key in REPORT_SECTION_KEYS:
        assert key in sections
        assert isinstance(sections[key], str)
        assert len(sections[key].strip()) > 0
