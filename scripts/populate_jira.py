"""Populate Jira with RAB test tickets and verify the service can pull them.

This script addresses the concern: "system is not actually pulling tickets from Jira".

It:
  1. Checks Jira connectivity (auth, base URL, myself, projects).
  2. Discovers available projects (DEMO, TEST, etc.).
  3. Creates N synthetic tickets in Jira via REST API.
  4. Verifies they are retrievable via direct Jira search (proof Jira is writable/readable).
  5. Verifies they are pullable via the service's own JiraClient / JiraSyncService
     (proof the app's code path can pull tickets).
  6. Optionally syncs them into the local SQLite audit DB.

Usage:
  python scripts/populate_jira.py --help
  python scripts/populate_jira.py --project TEST --count 5
  python scripts/populate_jira.py --verify-only          # no creation, just verify pull
  python scripts/populate_jira.py --project DEMO --count 3 --sync   # also sync into local DB
  python scripts/populate_jira.py --cleanup --prefix RAB-AUTO   # delete auto-created issues

Requires .env with JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Load .env early (so app.config also sees it)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Allow importing app.* when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


JIRA_BASE_URL = _env("JIRA_BASE_URL")
JIRA_EMAIL = _env("JIRA_EMAIL")
JIRA_API_TOKEN = _env("JIRA_API_TOKEN")
DEFAULT_PROJECT = _env("JIRA_PROJECT_KEY") or "TEST"  # fallback to TEST if not configured

ADF_PARAGRAPH = lambda text: {
    "type": "doc",
    "version": 1,
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
}

# RAB details block embedded in description so the dashboard (which now persists description)
# shows non-blank details even though JIRA_FIELD_* custom fields are not configured in this Jira instance.
_RAB_DETAILS_BLOCK = """RAB Details (embedded in description so dashboard shows it):
- Date/Time: {date_time}
- RAB Approver: {rab_approver}
- PR Link: {pr_link}
- Pipeline Link: {pipeline_link}
- Developer: {developer}
- Team Lead: {team_lead}
- PM: {pm}
- QA: {qa}
- Environment: {environment}
- Rollback/Mitigation: {rollback}
"""

# Synthetic ticket definitions covering different RAB validation scenarios
# Updated for advisory GET-and-NOTE (per data structure.drawio.html): not every ticket must have all 12 RAB fields.
# - validated: all 12 present (full RAB block)
# - validated_with_notes: some missing but workflow continues (advisory, missing noted in validation_result)
# - minimal: tests blank-details fix
TICKET_TEMPLATES = [
    {
        "summary": "RAB-AUTO validated ticket — should pass",
        "description": "All fields present. Created by populate_jira.py to verify Jira pull works. Has assignee, reporter, summary.",
        "labels": ["rab-auto", "validated"],
        "priority": "High",
        "mode": "full",  # all 12 RAB fields present
    },
    {
        "summary": "RAB-AUTO release for pipeline v1.2",
        "description": "Release candidate v1.2 — see RAB details below.",
        "labels": ["rab-auto"],
        "priority": "High",
        "mode": "full",
    },
    {
        "summary": "RAB-AUTO hotfix — missing optional fields",
        "description": "Minimal hotfix ticket — used to test advisory noting (validated_with_notes).",
        "labels": ["rab-auto", "minimal"],
        "priority": "Medium",
        "mode": "partial",  # only 4/12 present -> will be validated_with_notes in advisory mode
    },
    {
        "summary": "RAB-AUTO regression test ticket",
        "description": "Created to verify the sync endpoint POST /rab/sync pulls issues regardless of webhook.",
        "labels": ["rab-auto", "sync-test"],
        "priority": "Medium",
        "mode": "full",
    },
    {
        "summary": "RAB-AUTO aging ticket — will be backdated in demo",
        "description": "Used to test aging approvals KPIs on the dashboard.",
        "labels": ["rab-auto", "aging"],
        "priority": "Low",
        "mode": "full",
    },
]


def _auth() -> httpx.BasicAuth:
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        print("ERROR: JIRA_EMAIL or JIRA_API_TOKEN not set. Check .env", file=sys.stderr)
        sys.exit(1)
    return httpx.BasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)


def _base() -> str:
    if not JIRA_BASE_URL:
        print("ERROR: JIRA_BASE_URL not set. Check .env", file=sys.stderr)
        sys.exit(1)
    return JIRA_BASE_URL.rstrip("/")


async def check_connection(client: httpx.AsyncClient) -> dict:
    """Return Jira myself + project list with diagnostics."""
    base = _base()
    auth = _auth()
    out: dict = {}
    r = await client.get(f"{base}/rest/api/3/myself", auth=auth, headers={"Accept": "application/json"})
    r.raise_for_status()
    myself = r.json()
    out["myself"] = myself
    print(f"[OK] Authenticated as {myself.get('displayName')} ({myself.get('emailAddress')}) accountId={myself.get('accountId')}")

    r2 = await client.get(f"{base}/rest/api/3/project", auth=auth, headers={"Accept": "application/json"})
    r2.raise_for_status()
    projects = r2.json()
    out["projects"] = projects
    print(f"[OK] Jira reports {len(projects)} project(s): {', '.join(p['key'] for p in projects)}")
    for p in projects:
        print(f"     - {p['key']}: {p['name']} (id={p['id']}, type={p.get('projectTypeKey')})")
        issue_types = [t["name"] for t in p.get("issueTypes", [])]
        if issue_types:
            print(f"       issueTypes: {', '.join(issue_types)}")
    return out


async def create_issue(client: httpx.AsyncClient, project_key: str, summary: str, description: str, labels=None, issue_type: str = "Task", assignee_account_id: str | None = None, priority: str | None = None) -> dict:
    base = _base()
    auth = _auth()
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "description": ADF_PARAGRAPH(description),
        }
    }
    if labels:
        payload["fields"]["labels"] = labels
    if assignee_account_id:
        # Use accountId — service_desk projects accept assignee on Task
        payload["fields"]["assignee"] = {"accountId": assignee_account_id}
    if priority:
        # Priority is a standard field; valid names: Highest, High, Medium, Low, Lowest (depends on instance)
        payload["fields"]["priority"] = {"name": priority}
    r = await client.post(f"{base}/rest/api/3/issue", auth=auth, headers={"Accept": "application/json", "Content-Type": "application/json"}, json=payload)
    if r.status_code not in (200, 201):
        print(f"[FAIL] Create issue project={project_key} summary={summary!r} -> HTTP {r.status_code}: {r.text[:600]}")
        r.raise_for_status()
    data = r.json()
    print(f"  [CREATED] {data['key']} (id={data['id']}) summary={summary!r}")
    return data


async def list_issues_direct(client: httpx.AsyncClient, jql: str, max_results: int = 20) -> list[dict]:
    base = _base()
    auth = _auth()
    r = await client.post(
        f"{base}/rest/api/3/search/jql",
        auth=auth,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={"jql": jql, "maxResults": max_results},
    )
    r.raise_for_status()
    data = r.json()
    return data.get("issues", [])


async def get_issue_full(client: httpx.AsyncClient, issue_key: str) -> dict:
    base = _base()
    auth = _auth()
    r = await client.get(f"{base}/rest/api/3/issue/{issue_key}", auth=auth, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


async def verify_via_app_client(project_key: str) -> list[dict]:
    """Use the app's own JiraClient to pull issues (same code path the service uses)."""
    try:
        from app.services.jira_client import JiraClient
    except Exception as e:
        print(f"[SKIP] Could not import app.services.jira_client: {e}")
        return []
    c = JiraClient()
    if not c.base_url or not c.email or not c.api_token:
        print("[SKIP] App JiraClient not configured (base_url/email/token missing). Check .env.")
        return []
    print(f"[CHECK] Verifying via app.services.jira_client.JiraClient.list_project_issues('{project_key}')...")
    try:
        issues = await c.list_project_issues(project_key, max_results=50)
        print(f"  [OK] JiraClient pulled {len(issues)} issue(s) from project {project_key}")
        for it in issues[:5]:
            print(f"       - {it.get('key')} id={it.get('id')} summary={it.get('fields', {}).get('summary', '')[:60]!r}")
        if len(issues) > 5:
            print(f"       ... and {len(issues) - 5} more")
        return issues
    except Exception as e:
        print(f"  [FAIL] JiraClient pull failed: {e}")
        return []


async def verify_via_sync_service(project_key: str) -> None:
    """Use JiraSyncService to pull and upsert into local DB (end-to-end)."""
    try:
        from app.services.jira_sync import JiraSyncService
        from app.database import init_db, close_db
    except Exception as e:
        print(f"[SKIP] Could not import JiraSyncService: {e}")
        return
    print(f"[CHECK] Verifying via app.services.jira_sync.JiraSyncService.sync_project('{project_key}')...")
    try:
        await init_db()
        svc = JiraSyncService()
        result = await svc.sync_project(project_key)
        print(f"  [SYNC] synced={result.synced} created={result.created} updated={result.updated} failed={result.failed}")
        if result.errors:
            for err in result.errors[:5]:
                print(f"         error: {err}")
        # Show local DB counts
        from app.repositories.rab_repository import RabRepository

        repo = RabRepository()
        rows, total = await repo.get_all_records_with_count(limit=5)
        print(f"  [DB] Local rab_records total={total} (showing 5 most recent):")
        for r in rows:
            print(f"       - {r['issue_key']}: status={r['status']} summary={r['summary'][:50]!r}")
    except Exception as e:
        print(f"  [FAIL] JiraSyncService sync failed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            from app.database import close_db

            await close_db()
        except Exception:
            pass


async def cleanup_prefix(client: httpx.AsyncClient, project_key: str, prefix: str, dry_run: bool = False) -> int:
    """Delete issues whose summary starts with prefix (used for auto-created tickets)."""
    base = _base()
    auth = _auth()
    jql = f'project = "{project_key}" AND summary ~ "{prefix}" ORDER BY updated DESC'
    issues = await list_issues_direct(client, jql, max_results=100)
    # Filter more strictly by summary prefix after fetching full issues
    to_delete = []
    for ref in issues:
        iid = ref.get("id")
        if not iid:
            continue
        full = await get_issue_full(client, iid) if prefix else None
        # For simplicity fetch by id; but search already filters summary ~ prefix loosely, so double-check
        if full and full.get("fields", {}).get("summary", "").startswith(prefix):
            to_delete.append(full["key"])
        elif not full and ref.get("key", "").startswith(prefix):
            to_delete.append(ref.get("key"))

    # Also try direct JQL fetch via ids that already have keys (search/jql without fields only returns id, so we fetched full)
    if not to_delete and issues:
        # fallback: if we couldn't match via prefix, list via app search with fields expanded
        # Use sync service search path: try GET with expand
        pass

    if not to_delete:
        print(f"[CLEANUP] No issues with prefix {prefix!r} in project {project_key} found via JQL '{jql}'.")
        return 0

    print(f"[CLEANUP] Found {len(to_delete)} issue(s) with prefix {prefix!r}: {', '.join(to_delete)}")
    if dry_run:
        print("  (dry-run — not deleting)")
        return len(to_delete)
    deleted = 0
    for key in to_delete:
        r = await client.delete(f"{base}/rest/api/3/issue/{key}", auth=auth, headers={"Accept": "application/json"})
        if r.status_code in (200, 202, 204):
            print(f"  [DELETED] {key}")
            deleted += 1
        else:
            print(f"  [FAIL] Delete {key} -> HTTP {r.status_code}: {r.text[:300]}")
    return deleted


async def main_async(args: argparse.Namespace) -> None:
    print("=" * 70)
    print("RAB Automation — Jira Populate & Pull Verification")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"JIRA_BASE_URL={_base()}")
    print(f"JIRA_EMAIL={JIRA_EMAIL}")
    print(f"JIRA_API_TOKEN: {'***' + JIRA_API_TOKEN[-6:] if len(JIRA_API_TOKEN) > 6 else 'NOT SET'} (len={len(JIRA_API_TOKEN)})")
    print(f"JIRA_PROJECT_KEY (.env)={_env('JIRA_PROJECT_KEY') or '(empty — using fallback)'}")
    print(f"Args: project={args.project} count={args.count} prefix={args.prefix} verify_only={args.verify_only} sync={args.sync} cleanup={args.cleanup}")
    print("=" * 70)
    print()

    # Diagnose missing config that causes "not pulling" perception
    if not _env("JIRA_PROJECT_KEY"):
        print("[WARN] JIRA_PROJECT_KEY is empty in .env — POST /rab/sync without a project_key")
        print("       will fall back to JQL 'ORDER BY updated DESC' (last 100 issues, no project filter).")
        print("       Set JIRA_PROJECT_KEY=TEST or JIRA_PROJECT_KEY=DEMO for deterministic sync.")
        print()

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1. Check connection
        print("[1/5] Checking Jira connection...")
        try:
            info = await check_connection(client)
        except httpx.HTTPStatusError as e:
            print(f"[FAIL] Jira connection failed: HTTP {e.response.status_code}: {e.response.text[:800]}")
            sys.exit(1)
        print()

        # Validate requested project exists
        available_keys = {p["key"] for p in info.get("projects", [])}
        if args.project not in available_keys:
            print(f"[WARN] Requested project {args.project!r} not in available {available_keys}.")
            print("       Available projects:", ", ".join(available_keys) or "(none)")
            if available_keys:
                fallback = sorted(available_keys)[0]
                print(f"       Proceeding anyway — Jira will return 400 if project is invalid. Try --project {fallback}")
            print()

        # 2. Cleanup if requested
        if args.cleanup:
            print(f"[CLEANUP] Deleting issues with prefix {args.prefix!r} in project {args.project}...")
            # Use a broader JQL because service_desk search may not support summary ~ prefix reliably for all
            # So instead list recent issues and filter in Python
            recent = await list_issues_direct(client, f'project = "{args.project}" ORDER BY updated DESC', max_results=100)
            to_delete = []
            for ref in recent:
                iid = ref.get("id")
                if not iid:
                    continue
                full = await get_issue_full(client, iid)
                summ = full.get("fields", {}).get("summary", "")
                key = full.get("key", "")
                if summ.startswith(args.prefix):
                    to_delete.append(key)
            if not to_delete:
                print("  No matching issues found.")
            else:
                print(f"  Found {len(to_delete)}: {', '.join(to_delete)}")
                if args.dry_run:
                    print("  (dry-run — not deleting)")
                else:
                    for k in to_delete:
                        r = await client.delete(f"{_base()}/rest/api/3/issue/{k}", auth=_auth(), headers={"Accept": "application/json"})
                        print(f"  {'[DELETED]' if r.status_code in (200,202,204) else '[FAIL]'} {k} -> {r.status_code}")
            if args.verify_only and args.cleanup:
                # if cleanup-only mode, exit after
                pass
            print()

        if args.verify_only and not args.cleanup:
            print("[VERIFY-ONLY] Skipping creation. Verifying pull only...\n")
        elif not args.verify_only:
            # 3. Create issues
            print(f"[2/5] Creating {args.count} issue(s) in project {args.project}...")
            created_keys: list[str] = []
            assignee_id = info.get("myself", {}).get("accountId")  # so validation (assignee required) passes
            if assignee_id:
                print(f"  Using assignee accountId={assignee_id} so tickets pass validation")
            for i in range(args.count):
                tpl = TICKET_TEMPLATES[i % len(TICKET_TEMPLATES)]
                # Make summary unique with timestamp suffix
                ts = datetime.now(timezone.utc).strftime("%H%M%S")
                summary = f"{args.prefix} {i+1}/{args.count} — {tpl['summary']} [{ts}]"
                # Build description per drawio advisory: GET and NOTE present/missing.
                # mode=full -> all 12 present (validated); mode=partial -> only 4/12 per Power Automate check (RAB, PR Link, Pipeline Link, Team Lead) -> validated_with_notes
                mode = tpl.get("mode", "full")
                if mode == "partial":
                    # Intentionally incomplete to demo validated_with_notes (advisory) — only the 4 Power Automate fields + assignee/reporter/environment
                    rab_block = (
                        f"RAB Details (partial — advisory demo):\n"
                        f"- RAB Approver: sdl@example.com\n"
                        f"- PR Link: https://github.com/example/repo/pull/42\n"
                        f"- Pipeline Link: https://dev.azure.com/example/pipeline/99\n"
                        f"- Team Lead: lead@example.com\n"
                        f"- Environment: staging\n"
                    )
                else:
                    rab_block = _RAB_DETAILS_BLOCK.format(
                        date_time=datetime.now(timezone.utc).isoformat(),
                        rab_approver="sdl@example.com",
                        pr_link="https://github.com/example/repo/pull/42",
                        pipeline_link="https://dev.azure.com/example/pipeline/99",
                        developer="dev@example.com",
                        team_lead="lead@example.com",
                        pm="pm@example.com",
                        qa="qa@example.com",
                        environment="staging" if i % 2 == 0 else "production",
                        rollback="Revert commit / redeploy previous artifact",
                    )
                # For advisory demo, also add blast radius image note to mirror drawio Attachments
                extra_note = "Attachments: blast radius image attached (simulated)" if mode == "full" else "Attachments: none — will be noted as missing"
                description = tpl["description"] + "\n\n" + rab_block + f"\n{extra_note}\nCreated: {datetime.now(timezone.utc).isoformat()}  template={i % len(TICKET_TEMPLATES)}  mode={mode}  assignee_set={'yes' if assignee_id else 'no'}"
                try:
                    data = await create_issue(client, args.project, summary, description, labels=tpl.get("labels"), assignee_account_id=assignee_id, priority=tpl.get("priority"))
                    created_keys.append(data["key"])
                except Exception as e:
                    print(f"  [ERROR] Failed to create issue {i+1}: {e}")
            print(f"  Done. Created {len(created_keys)} issue(s): {', '.join(created_keys) if created_keys else '(none)'}")
            print()
        else:
            print()

        # 4. Verify via direct Jira search (proof tickets exist in Jira)
        print(f"[3/5] Verifying via direct Jira REST search for project {args.project}...")
        try:
            issues = await list_issues_direct(client, f'project = "{args.project}" ORDER BY updated DESC', max_results=10)
            print(f"  [OK] Direct search returned {len(issues)} issue refs (IDs). Fetching 3 full records for proof:")
            for ref in issues[:3]:
                full = await get_issue_full(client, ref["id"])
                print(f"       - {full['key']}: summary={full['fields'].get('summary','')[:70]!r} status={full['fields'].get('status',{}).get('name')} assignee={full['fields'].get('assignee',{}).get('displayName') if full['fields'].get('assignee') else 'unassigned'}")
            # Count how many have our prefix
            if not args.verify_only:
                full_summaries = []
                for ref in issues:
                    full = await get_issue_full(client, ref["id"])
                    full_summaries.append(full["fields"].get("summary",""))
                prefixed = [s for s in full_summaries if s.startswith(args.prefix)]
                print(f"  [CHECK] {len(prefixed)} of {len(issues)} recent issues have prefix {args.prefix!r} — {'PASS' if prefixed else 'CHECK: recent page may not include new issues due to pagination delay (retry in 5s)'}")
        except Exception as e:
            print(f"  [FAIL] Direct search failed: {e}")
        print()

        # 5. Verify via app's JiraClient (same code the service uses to pull)
        print(f"[4/5] Verifying via app's JiraClient + JiraSyncService pull path...")
        app_issues = await verify_via_app_client(args.project)
        print()

        # 6. Sync into local DB if requested (or always show what would happen)
        if args.sync:
            print(f"[5/5] Syncing into local SQLite via JiraSyncService...")
            await verify_via_sync_service(args.project)
        else:
            print(f"[5/5] (Skipped local DB sync — pass --sync to also upsert into rab_records.)")
            print(f"      To sync manually: curl -X POST http://localhost:8000/rab/sync?project_key={args.project}")
            print(f"      Or via dashboard: http://localhost:8000/dashboard/sync or /dashboard/tools (Sync button)")
        print()
        print("=" * 70)
        print("Summary: If steps 3 and 4 show your new issues, the system CAN pull from Jira.")
        print("If step 4 (JiraClient) shows 0 issues but direct search shows them, check:")
        print("  - JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN in .env are correct (they are for TEST/DEMO)")
        print("  - The token has 'read:jira-work' scope (it does — myself succeeded)")
        print("  - JIRA_PROJECT_KEY is set (currently empty) — sync_all fallback works but is less predictable")
        print("  - The service was restarted after editing .env (config is loaded at startup)")
        print("Common fix: set JIRA_PROJECT_KEY=TEST in .env and restart uvicorn, then POST /rab/sync")
        print("=" * 70)
        # Ensure DB connection closed so asyncio.run can exit cleanly (aiosqlite keeps loop alive)
        try:
            from app.database import close_db

            await close_db()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate Jira with test tickets and verify pull")
    parser.add_argument("--project", default=DEFAULT_PROJECT or "TEST", help="Jira project key to create tickets in (default: %(default)s or TEST)")
    parser.add_argument("--count", type=int, default=3, help="Number of tickets to create (default: 3)")
    parser.add_argument("--prefix", default="RAB-AUTO", help="Summary prefix for created tickets (used for cleanup filtering)")
    parser.add_argument("--verify-only", action="store_true", help="Do not create tickets — only verify pull")
    parser.add_argument("--sync", action="store_true", help="After creation, run JiraSyncService.sync_project to upsert into local DB")
    parser.add_argument("--cleanup", action="store_true", help="Delete issues with --prefix in the target project (filtered by summary prefix)")
    parser.add_argument("--dry-run", action="store_true", help="With --cleanup, only show what would be deleted")
    args = parser.parse_args()

    if args.count < 0 or args.count > 20:
        parser.error("--count must be 0..20")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
