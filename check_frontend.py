import urllib.request

# Test root
try:
    with urllib.request.urlopen("http://localhost:5173/", timeout=5) as r:
        print(f"GET / => {r.status}")
        content = r.read().decode('utf-8', errors='replace')
        print(content[:200])
except Exception as e:
    print(f"GET / => ERROR: {e}")

# Test index.html directly
try:
    with urllib.request.urlopen("http://localhost:5173/index.html", timeout=5) as r:
        print(f"\nGET /index.html => {r.status}")
        content = r.read().decode('utf-8', errors='replace')
        print(content[:200])
except Exception as e:
    print(f"GET /index.html => ERROR: {e}")

# Test /src/main.jsx
try:
    with urllib.request.urlopen("http://localhost:5173/src/main.jsx", timeout=5) as r:
        print(f"\nGET /src/main.jsx => {r.status}")
except Exception as e:
    print(f"GET /src/main.jsx => ERROR: {e}")
