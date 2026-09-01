import os
import httpx
from dotenv import load_dotenv

load_dotenv()
base = os.environ["JIRA_BASE_URL"].rstrip("/")
auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
field_ids = [
    "customfield_10123", "customfield_10124", "customfield_10125", "customfield_10126",
    "customfield_10127", "customfield_10128", "customfield_10129", "customfield_10130",
    "customfield_10131", "customfield_10132", "customfield_10133", "customfield_10134",
    "customfield_10135", "customfield_10136", "customfield_10137", "customfield_10138",
    "customfield_10000", "customfield_10139", "customfield_10020",
]

with httpx.Client(auth=auth, timeout=30, headers={"Accept": "application/json", "Content-Type": "application/json"}) as client:
    existing = client.get(f"{base}/rest/api/3/screens/10004/tabs/10007/fields")
    existing.raise_for_status()
    present = {item["id"] for item in existing.json()}
    for field_id in field_ids:
        if field_id in present:
            print(f"exists  {field_id}")
            continue
        response = client.post(f"{base}/rest/api/3/screens/10004/tabs/10007/fields", json={"fieldId": field_id})
        if response.status_code >= 400:
            print(f"failed  {field_id}: {response.status_code} {response.text[:300]}")
        else:
            print(f"added   {field_id}")
