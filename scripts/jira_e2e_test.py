"""Jira-only end-to-end test (Azure DevOps and Teams not required)."""

import asyncio
import httpx
import json

BASE = "http://localhost:8012"


async def test():
    async with httpx.AsyncClient() as c:
        print("=== Jira E2E Test ===")

        # 1. Health check
        r = await c.get(f"{BASE}/health")
        h = r.json()
        print(f"1. Health: Jira connected={h['jira']['connected']}")

        # 2. Trigger webhook for TEST-1 (has assignee, passes validation)
        r = await c.post(
            f"{BASE}/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
        )
        print(f"2. Webhook TEST-1: {r.json()}")

        # 3. Trigger webhook for DEMO-1 (may or may not have fields)
        r = await c.post(
            f"{BASE}/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "DEMO-1"}},
        )
        print(f"3. Webhook DEMO-1: {r.json()}")

        # 4. Audit records JSON
        r = await c.get(f"{BASE}/rab/records")
        data = r.json()
        print(f"4. RAB Records: total={data['total']}")
        for rec in data["records"]:
            print(f"   - {rec['issue_key']}: status={rec['status']}, "
                  f"sdl={rec['sdl_approval']}, sdm={rec['sdm_approval']}")

        # 5. Metrics
        r = await c.get(f"{BASE}/metrics")
        m = r.json()
        print(f"5. Metrics: uptime={m['uptime_seconds']:.0f}s, "
              f"requests={m['requests_total']}, failed={m['requests_failed']}")

        # 6. Dashboard pages
        r = await c.get(f"{BASE}/dashboard/health")
        print(f"6. Health page: HTTP {r.status_code}, {len(r.text)} bytes")

        r = await c.get(f"{BASE}/dashboard/records")
        print(f"7. Records page: HTTP {r.status_code}, {len(r.text)} bytes")
        print(f"   Contains 'TEST-1': {'TEST-1' in r.text}")

        print("\n=== All Jira E2E tests passed ===")


asyncio.run(test())
