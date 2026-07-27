import sys
sys.path.insert(0, r'd:\e drive\Only_Project\dr_cnn')
import src.chatbot.bot as bot
prompt = bot.build_report_prompt('Mild', request_id='test', lang='en')
print('notes_in_prompt', 'Notes' in prompt)
sample = '{"Clinical Interpretation":"A detailed interpretation of retinal findings showing mild vascular changes and early diabetic retinopathy.","Disease Summary":"The assessment indicates mild non-proliferative changes with stable retinal anatomy and limited progression risk.","Possible Medical Concerns":"The patient may require closer follow-up if glycemic control worsens or visual symptoms increase.","Treatment Guidance":"Ophthalmologic monitoring and medical management should be coordinated with the primary care team.","Lifestyle Recommendations":"Maintain blood sugar control, hydration, regular activity, and avoid smoking while following the clinician plan.","Follow-up Advice":"Schedule a re-evaluation in three months or sooner if symptoms change.","Medical Disclaimer":"This report supports clinical discussion and is not a substitute for direct medical evaluation.","Notes":"Document any new visual distortion, sudden blurring, or pain for urgent review."}'
sections = bot.extract_report_sections(sample)
print('sections', sections)
print('count', len(sections) if isinstance(sections, dict) else 'n/a')
