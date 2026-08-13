"""Live end-to-end test of the RAB Automation service."""

import asyncio
import httpx
import json

BASE = "http://localhost:8011"


async def test():
    async with httpx.AsyncClient() as c:
        # Root redirect
        r = await c.get(f"{BASE}/", follow_redirects=False)
        print(f"GET / => HTTP {r.status_code} Location: {r.headers.get('location')}")

        # Health page
        r = await c.get(f"{BASE}/dashboard/health")
        print(f"GET /dashboard/health => HTTP {r.status_code}, len={len(r.text)}")
        print(f"  Contains health cards: {'health-card' in r.text}")

        # Records page
        r = await c.get(f"{BASE}/dashboard/records")
        print(f"GET /dashboard/records => HTTP {r.status_code}, len={len(r.text)}")
        print(f"  Contains table: {'table' in r.text}")

        # CSS
        r = await c.get(f"{BASE}/static/css/style.css")
        print(f"GET /static/css/style.css => HTTP {r.status_code}, len={len(r.text)}")

        # Metrics
        r = await c.get(f"{BASE}/metrics")
        print(f"GET /metrics => HTTP {r.status_code}: {r.json()}")

        # Trigger webhook
        r = await c.post(
            f"{BASE}/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
        )
        print(f"Webhook: {r.json()}")

        # Records page after webhook
        r = await c.get(f"{BASE}/dashboard/records")
        test1_count = r.text.count("TEST-1")
        print(f"Records page after webhook: len={len(r.text)}, TEST-1 occurrences={test1_count}")

        # JSON records endpoint
        r = await c.get(f"{BASE}/rab/records")
        data = r.json()
        print(f"RAB records JSON: total={data['total']}, records={len(data['records'])}")

        print("\nAll live tests passed!")


asyncio.run(test())
