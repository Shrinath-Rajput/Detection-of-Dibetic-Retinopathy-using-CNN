from app import app

with app.test_client() as c:
    resp = c.get('/download_dr_pdf')
    print('status', resp.status_code)
    print('content-type', resp.headers.get('Content-Type'))
    print('content-disposition', resp.headers.get('Content-Disposition'))
    print('content-length', resp.headers.get('Content-Length'))
    data = resp.data
    print('len data', len(data))
    open('test_retina3.pdf','wb').write(data)
print('done')
