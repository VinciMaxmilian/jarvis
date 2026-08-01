import os, httpx, json
key = os.environ.get('GEMINI_API_KEY')
if not key:
    with open('.env') as f:
        for line in f:
            if line.startswith('GEMINI_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
payload = {
    'contents': [{'role': 'user', 'parts': [{'text': 'what is the weather in tokyo?'}]}],
    'tools': [{'functionDeclarations': [{'name': 'get_weather', 'description': 'get weather', 'parameters': {'type': 'object', 'properties': {'location': {'type': 'string'}}}}]}]
}
resp = httpx.post(url, json=payload, headers={'Content-Type': 'application/json', 'x-goog-api-key': key}, timeout=10)
print(json.dumps(resp.json(), indent=2))
