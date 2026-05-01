import requests
import json

base = "http://localhost:8000"

# Test get_masters
try:
    r = requests.post(f"{base}/api/get_services", json={"init_data":"dev_init_data_simulation","tenant_id":1}, timeout=5)
    print("GET /services ->", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print(f"Services: {len(data)} items")
        for s in data:
            print(f"  {s['name']} - {s['price']} uah")
except Exception as e:
    print("Error:", e)

# Test get_masters
try:
    r = requests.get(f"{base}/api/masters?init_data=dev_init_data_simulation&tenant_id=1", timeout=5)
    print("\nGET /masters ->", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print(f"Masters: {len(data)} items")
        for m in data:
            print(f"  {m['name']} - {m.get('specialty','')}")
except Exception as e:
    print("Error:", e)

# Test get_available_slots (for service 1, master 1, today)
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")
try:
    url = f"{base}/api/available_slots?init_data=dev_init_data_simulation&tenant_id=1&service_id=1&master_id=1&date={today}"
    r = requests.get(url, timeout=5)
    print(f"\nGET /available_slots ->", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print(f"Slots: {len(data)} items")
        for s in data:
            print(f"  {s['time']} (master {s['master_name']})")
except Exception as e:
    print("Error:", e)
