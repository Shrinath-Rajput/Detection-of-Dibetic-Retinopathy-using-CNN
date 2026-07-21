import os
from app import app

candidate = None
for root, dirs, files in os.walk('static'):
    for f in files:
        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
            candidate = os.path.join(root, f)
            break
    if candidate:
        break

if not candidate:
    raise SystemExit('No sample image found in static folder')

print('sample', candidate)

with app.test_client() as client:
    with open(candidate, 'rb') as img:
        data = {'image': (img, os.path.basename(candidate))}
        resp = client.post('/predict', data=data, content_type='multipart/form-data', follow_redirects=False)
        print('POST', resp.status_code)
        print('Location', resp.headers.get('Location'))
        if resp.status_code == 302:
            resp2 = client.get(resp.headers['Location'])
            print('GET redirected', resp2.status_code)
            print('result length', len(resp2.data))
        else:
            print(resp.data[:500])
    resp3 = client.get('/download_dr_pdf')
    print('PDF', resp3.status_code, resp3.headers.get('Content-Type'), resp3.headers.get('Content-Disposition'))
    open('debug_retina_report.pdf', 'wb').write(resp3.data)
    print('saved', len(resp3.data))
