import urllib.request
import json

base = "http://localhost:8000"
init_data = "dev_init_data_simulation"

def test_endpoint(method, path, body=None):
    try:
        data = json.dumps(body).encode('utf-8') if body else None
        req = urllib.request.Request(
            f"{base}{path}",
            data=data,
            headers={'Content-Type': 'application/json'} if data else {},
            method=method
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            content = r.read().decode('utf-8')
            print(f"{method} {path} -> {r.status}")
            print(f"  Response: {content[:200]}")
            return r.status, json.loads(content)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        print(f"{method} {path} -> {e.code} ERROR: {err_body}")
        return e.code, None
    except Exception as e:
        print(f"{method} {path} -> EXC: {e}")
        return None, None

# 1. GET services
test_endpoint("POST", "/api/get_services", {"init_data":init_data,"tenant_id":1})

# 2. GET masters
test_endpoint("GET", f"/api/masters?init_data={init_data}&tenant_id=1")

# 3. GET available slots (today, service 1, master 1)
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")
url = f"/api/available_slots?init_data={init_data}&tenant_id=1&service_id=1&master_id=1&date={today}"
test_endpoint("GET", url)
