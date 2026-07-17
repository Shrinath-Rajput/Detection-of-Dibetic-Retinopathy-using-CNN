import requests
r = requests.get('http://127.0.0.1:5000/download_dr_pdf')
print('status', r.status_code)
for k,v in r.headers.items():
    print(f'{k}: {v}')
print('len body', len(r.content))
open('test_retina2.pdf','wb').write(r.content)
print('wrote test_retina2.pdf')
