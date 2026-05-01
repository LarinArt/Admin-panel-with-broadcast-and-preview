import http.client

conn = http.client.HTTPConnection("localhost", 5173, timeout=5)
conn.request("GET", "/", headers={"Accept": "text/html"})
response = conn.getresponse()
print(f"Status: {response.status} {response.reason}")
print(f"Headers: {dict(response.headers)}")
body = response.read().decode('utf-8', errors='replace')
print(f"Body length: {len(body)}")
print(f"Body preview: {body[:300]}")
conn.close()
