import http.client

conn = http.client.HTTPConnection("localhost", 5173, timeout=5)
conn.request("GET", "/", headers={
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})
resp = conn.getresponse()
print(f"Status: {resp.status}")
print(f"Content-Type: {resp.getheader('Content-Type')}")
body = resp.read().decode('utf-8', errors='replace')
print(f"Body length: {len(body)}")
print(body[:300])
conn.close()
