import os
from pathlib import Path

from app import app
from flask import session

OUTPUT_DIR = Path("pdf_verification_samples")
OUTPUT_DIR.mkdir(exist_ok=True)

sample_session = {
    'dr_prediction': 'Moderate DR',
    'dr_image_name': None,
    'diabetes_prediction': 'Type 2 Diabetes',
    'diabetes_risk_score': 72,
    'diabetes_recommendations': 'Maintain diet; exercise daily; consult doctor.',
    'pcod_prediction': 'Possible PCOD',
    'pcod_risk_score': 68,
    'migraine_prediction': 'Chronic Migraine',
    'migraine_risk_score': 64,
}

endpoints = [
    '/download_dr_pdf',
    '/download_diabetes_pdf',
    '/download_pcod_pdf',
    '/download_migraine_pdf',
]
langs = ['en', 'hi', 'mr']

print('Generating PDFs...')

with app.test_client() as client:
    for lang in langs:
        for endpoint in endpoints:
            with client.session_transaction() as sess:
                sess['lang'] = lang
                sess.update(sample_session)
            resp = client.get(endpoint)
            fname = OUTPUT_DIR / f'sample_{lang}_{endpoint[1:]}.pdf'
            ok = resp.status_code == 200 and resp.data[:4] == b'%PDF'
            print(lang, endpoint, 'status', resp.status_code, 'ok', ok, 'size', len(resp.data))
            if ok:
                fname.write_bytes(resp.data)
            else:
                raise RuntimeError(f'PDF generation failed for {lang} {endpoint}')

try:
    import PyPDF2
except ImportError:
    raise

print('\nInspecting generated PDFs...')
for pdf_file in sorted(OUTPUT_DIR.glob('*.pdf')):
    print('\nFILE:', pdf_file)
    with open(pdf_file, 'rb') as f:
        data = f.read()
    fonts = set()
    for marker in [b'/FontName', b'/Font', b'/BaseFont']:
        start = 0
        while True:
            idx = data.find(marker, start)
            if idx == -1:
                break
            # read the token following the marker
            substr = data[idx:idx+100]
            try:
                decoded = substr.decode('latin1')
            except Exception:
                decoded = repr(substr)
            fonts.add(decoded)
            start = idx + len(marker)
    print('Font markers found:', len(fonts))
    for f in sorted(fonts):
        if 'Deva' in f or 'Nirmala' in f or 'Helvetica' in f or 'Times' in f or 'Courier' in f:
            print(' ', f)
    # text extraction
    reader = PyPDF2.PdfReader(str(pdf_file))
    extracted = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        extracted.append(text)
        snippet = text[:200].replace('\n', ' ') if text else '<none>'
        print(' page', i+1, 'text len', len(text), 'snippet', snippet)
    text_total = '\n'.join(extracted)
    if '□' in text_total:
        print('WARNING: found square box character in extracted text')
    if '\ufffd' in text_total:
        print('WARNING: found replacement char in extracted text')
    if 'DevaNirmala_ttc' not in data.decode('latin1', errors='ignore') and 'Nirmala' not in data.decode('latin1', errors='ignore'):
        print('WARNING: Nirmala font not found in raw PDF bytes')

print('\nVerification script completed.')
