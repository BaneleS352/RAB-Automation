#!/usr/bin/env python3
"""Detect whether a Jira API token is classic (unscoped) or scoped.

Usage:
    python scripts/check_token_type.py
    # Reads JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN from environment

    python scripts/check_token_type.py --base-url https://yourcompany.atlassian.net \\
                                       --email user@company.com --token <token>
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


async def try_classic(base_url: str, email: str, token: str) -> dict:
    url = f"{base_url.rstrip('/')}/rest/api/3/myself"
    auth = httpx.BasicAuth(email, token)
    headers = {"Accept": "application/json"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, auth=auth, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {"type": "classic", "detail": f"Authenticated as {data.get('displayName', '?')} ({data.get('emailAddress', '?')})"}
            if resp.status_code == 401:
                return {"type": None, "detail": "Classic endpoint returned HTTP 401 - token rejected (may be scoped token or wrong credentials)"}
            return {"type": None, "detail": f"Classic endpoint returned HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"type": None, "detail": f"Could not connect to {base_url} - check the URL"}
    except httpx.RequestError as e:
        return {"type": None, "detail": f"Network error: {e}"}


async def try_scoped_via_gateway(email: str, token: str) -> dict:
    url = "https://api.atlassian.com/oauth/token/accessible-resources"
    auth = httpx.BasicAuth(email, token)
    headers = {"Accept": "application/json"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, auth=auth, headers=headers, timeout=10)
            if resp.status_code == 401:
                return {"type": None, "detail": "Scoped gateway returned HTTP 401 - token rejected or not a scoped token"}
            if resp.status_code == 404:
                return {"type": None, "detail": "Scoped gateway URL not found (this endpoint may not be available for this account type)"}
            if resp.status_code != 200:
                return {"type": None, "detail": f"Scoped gateway returned HTTP {resp.status_code}"}

            resources = resp.json()
            if not resources:
                return {"type": None, "detail": "Scoped gateway returned empty list - no Jira sites accessible with this token"}

            for r in resources:
                cloud_id = r["id"]
                site_name = r.get("name", r.get("url", cloud_id))
                site_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"

                site_resp = await client.get(site_url, auth=auth, headers=headers, timeout=10)
                if site_resp.status_code == 200:
                    data = site_resp.json()
                    return {
                        "type": "scoped",
                        "cloud_id": cloud_id,
                        "site_name": site_name,
                        "detail": f"Authenticated as {data.get('displayName', '?')} on site '{site_name}'",
                    }

            return {"type": None, "detail": "Scoped gateway found resources but none accepted authentication"}
    except httpx.RequestError as e:
        return {"type": None, "detail": f"Network error: {e}"}


async def main() -> None:
    # Load .env from project root (parent of scripts/)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"(Loaded env from {env_path})")
        print()

    parser = argparse.ArgumentParser(description="Detect Jira API token type (classic vs scoped)")
    parser.add_argument("--base-url", default=os.getenv("JIRA_BASE_URL"), help="Jira site URL (e.g. https://yourcompany.atlassian.net)")
    parser.add_argument("--email", default=os.getenv("JIRA_EMAIL"), help="Atlassian account email")
    parser.add_argument("--token", default=os.getenv("JIRA_API_TOKEN"), help="Jira API token")
    args = parser.parse_args()

    missing = []
    if not args.base_url:
        missing.append("JIRA_BASE_URL")
    if not args.email:
        missing.append("JIRA_EMAIL")
    if not args.token:
        missing.append("JIRA_API_TOKEN")

    if missing:
        print("Error: missing required variable(s):")
        for var in missing:
            print(f"  - {var}")
        print("Pass them as --base-url, --email, --token flags or set as environment variables.")
        sys.exit(1)

    masked = f"{args.token[:6]}...{args.token[-4:]}" if len(args.token) > 10 else "(too short)"
    print(f"Checking Jira API token...")
    print(f"  Site:  {args.base_url}")
    print(f"  Email: {args.email}")
    print(f"  Token: {masked}")
    print()

    # --- Step 1: Try classic endpoint ---
    print("1. Trying classic endpoint (site-based URL)...")
    result = await try_classic(args.base_url, args.email, args.token)
    if result["type"] == "classic":
        print(f"   [OK] {result['detail']}")
        print()
        print(f"   Token type: CLASSIC (unscoped)")
        print(f"   URL format: {args.base_url.rstrip('/')}/rest/api/3/...")
        print()
        print("   This works with the current JiraClient as-is.")
        return

    print(f"   [FAIL] {result['detail']}")
    print()

    # --- Step 2: Try scoped via gateway ---
    print("2. Trying scoped endpoint (api.atlassian.com gateway)...")
    result = await try_scoped_via_gateway(args.email, args.token)
    if result["type"] == "scoped":
        print(f"   [OK] {result['detail']}")
        print()
        print(f"   Token type: SCOPED")
        print(f"   Cloud ID:   {result['cloud_id']}")
        print(f"   Site name:  {result['site_name']}")
        print(f"   URL format: https://api.atlassian.com/ex/jira/{{cloudId}}/rest/api/3/...")
        print()
        print("   [WARN] This token will NOT work with the current JiraClient.")
        print("   The JiraClient needs to be updated to detect scoped tokens")
        print("   and use the gateway URL with the cloud ID.")
        return

    print(f"   [FAIL] {result['detail']}")
    print()

    # --- Neither worked ---
    print("[FAIL] Could not authenticate with this token using either method.")
    print("  Check that the email, token, and base URL are correct.")
    print("  Also verify the token hasn't expired (classic tokens expire after 1 year).")


if __name__ == "__main__":
    asyncio.run(main())
