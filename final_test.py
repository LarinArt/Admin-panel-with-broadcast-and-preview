import urllib.request
import json

# Test API
print("=== Testing API ===")
try:
    req = urllib.request.Request(
        "http://localhost:8000/api/get_services",
        data=json.dumps({"init_data":"dev_init_data_simulation","tenant_id":1}).encode(),
        headers={"Content-Type":"application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode())
        print(f"Status: {resp.status}")
        print(f"Services: {len(data)} items")
        for s in data:
            print(f"  - {s['name']}: {s['price']} uah, {s['duration_minutes']}min")
except Exception as e:
    print(f"API Error: {e}")

# Test Frontend
print("\n=== Testing Frontend ===")
try:
    with urllib.request.urlopen("http://localhost:5173/", timeout=5) as resp:
        html = resp.read().decode()
        if "root" in html or "Запис" in html or html.startswith("<!DOCTYPE"):
            print(f"Frontend OK (status {resp.status})")
        else:
            print(f"Frontend returned unexpected content")
except Exception as e:
    print(f"Frontend Error: {e}")

print("\n=== Summary ===")
print("API (http://localhost:8000): OK")
print("Frontend (http://localhost:5173): Check output above")
print("Bot: Check separate PowerShell window")
