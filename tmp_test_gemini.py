import os, requests
from dotenv import load_dotenv
load_dotenv(dotenv_path=r'd:\e drive\Only_Project\dr_cnn\.env')
key = os.getenv('GEMINI_API_KEY')
for model in ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-2.0-flash', 'gemini-2.5-flash']:
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload = {'contents':[{'role':'user','parts':[{'text':'Say hello in one word'}]}],'generationConfig':{'temperature':0.2,'maxOutputTokens':20}}
    headers = {'Content-Type':'application/json','x-goog-api-key': key}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print(model, r.status_code)
    print(r.text[:800])
    print('---')
