import os
from app import app

# Use Flask test client to simulate upload + PDF download
with app.test_client() as client:
    test_image_path = None
    for root, _, files in os.walk('static'):
        for name in files:
            if name.lower().endswith(('.png', '.jpg', '.jpeg')):
                test_image_path = os.path.join(root, name)
                break
        if test_image_path:
            break
    if not test_image_path:
        raise FileNotFoundError('No sample image found in static/')

    with open(test_image_path, 'rb') as img:
        data = {'image': (img, os.path.basename(test_image_path))}
        resp = client.post('/predict', data=data, content_type='multipart/form-data', follow_redirects=True)
        print('POST /predict status', resp.status_code)
        print('redirected to', resp.request.path)
        assert resp.status_code == 200

        resp2 = client.get('/download_dr_pdf')
        print('GET /download_dr_pdf status', resp2.status_code)
        print('content-type', resp2.headers.get('Content-Type'))
        print('content-disposition', resp2.headers.get('Content-Disposition'))
        assert resp2.status_code == 200
        open('debug_retina_report.pdf', 'wb').write(resp2.data)
        print('Wrote debug_retina_report.pdf', len(resp2.data))
