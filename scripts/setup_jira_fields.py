"""Helper to diagnose and address empty/not-mapped RAB fields.

Checks the current .env JIRA_FIELD_* mappings, queries live Jira for available fields,
shows which RAB logical fields are empty vs mapped, and prints recommended .env lines.

Also explains the new description fallback: when a JIRA_FIELD_* is empty, the validator
now parses the Jira issue description for a "RAB Details" block (populated by
populate_jira.py), so tickets no longer appear blank even without custom fields.

Usage:
  python scripts/setup_jira_fields.py
  python scripts/setup_jira_fields.py --fix-env   # appends missing defaults to .env
"""
from __future__ import annotations
import os, sys, asyncio, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

import httpx
from app.config import get_settings
from app.services.field_validator import REQUIRED_FIELDS

JIRA_FIELD_VARS = [
    ("Date/Time", "JIRA_FIELD_DATE_TIME"),
    ("RAB Approver", "JIRA_FIELD_RAB_APPROVER"),
    ("Assignee", "JIRA_FIELD_PR_LINK"), # dummy
]

# Map logical keys to env vars
LOGICAL_TO_ENV = {
    "date_time": "JIRA_FIELD_DATE_TIME",
    "rab_approver": "JIRA_FIELD_RAB_APPROVER",
    "pr_link": "JIRA_FIELD_PR_LINK",
    "pipeline_link": "JIRA_FIELD_PIPELINE_LINK",
    "developer": "JIRA_FIELD_DEVELOPER",
    "team_lead": "JIRA_FIELD_TEAM_LEAD",
    "pm": "JIRA_FIELD_PM",
    "qa": "JIRA_FIELD_QA",
    "environment": "JIRA_FIELD_ENVIRONMENT",
    "rollback_details": "JIRA_FIELD_ROLLBACK_DETAILS",
}

def _env(name): return os.getenv(name, "").strip()

async def fetch_fields():
    base = _env("JIRA_BASE_URL")
    if not base:
        print("JIRA_BASE_URL not set — cannot query Jira.")
        return []
    auth = httpx.BasicAuth(_env("JIRA_EMAIL"), _env("JIRA_API_TOKEN"))
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(base.rstrip("/")+"/rest/api/3/field", auth=auth, headers={"Accept":"application/json"})
        r.raise_for_status()
        return r.json()

def print_report(fields):
    s = get_settings()
    print("="*70)
    print("RAB field mapping audit — empty / not mapped")
    print("="*70)
    print(f"JIRA_BASE_URL: {s.JIRA_BASE_URL}")
    print(f"JIRA_PROJECT_KEY: {s.JIRA_PROJECT_KEY or '(empty)'}")
    print()
    # Build lookup for Jira fields by name (lower)
    by_name = {f["name"].lower(): f for f in fields}
    by_id = {f["id"]: f for f in fields}

    print("Logical RAB field -> env var -> current value -> status")
    print("-"*70)
    empty_count = 0
    for display, key in REQUIRED_FIELDS:
        env = LOGICAL_TO_ENV.get(key) or f"JIRA_FIELD_{key.upper()}"
        # For assignee/reporter, they are standard fields, not env-mapped in same way
        if key in ("assignee","reporter"):
            val = key  # standard
            status = "OK (standard field)"
        else:
            val = getattr(s, env, "")
            if not val:
                empty_count+=1
                status = "EMPTY -> will use description fallback (was blank before fix)"
            else:
                # Check if mapped id/name actually exists in Jira
                if val in by_id:
                    status = f"MAPPED -> {by_id[val]['name']} ({val})"
                elif val.lower() in by_name:
                    status = f"MAPPED -> {by_name[val.lower()]['id']} ({val})"
                elif val in ("environment", "summary","description","labels","priority"):
                    status = f"MAPPED -> standard field '{val}'"
                else:
                    status = f"MAPPED but ID '{val}' not found in Jira field list — may be invalid"
        print(f"  {display:30} {env:30} {(val or '(empty)'):20} {status}")

    print()
    print(f"Summary: {empty_count}/10 custom RAB mappings empty (assignee/reporter are standard and always OK).")
    if empty_count>=8:
        print("  -> Previously this caused 10 fields to be skipped and dashboard raw_fields=null (blank). Now fallback parses description.")
    print()
    print("Available Jira fields that could be used for mapping:")
    print("-"*70)
    # Suggest candidates: textfield, url, select, user
    candidates = []
    for f in fields:
        fid = f["id"]
        name = f["name"]
        schema = f.get("schema",{}).get("type","")
        custom = f.get("schema",{}).get("custom","")
        if fid.startswith("customfield") and schema in ("string","option","array","user","any"):
            candidates.append((fid, name, schema))
        if fid in ("environment","summary","description"):
            candidates.append((fid, name, schema))
    for fid,name,schema in candidates[:20]:
        print(f"  {fid:20} {name:35} ({schema})")
    if len(candidates)>20:
        print(f"  ... and {len(candidates)-20} more (run with --full to see all)")
    print()
    print("Recommended .env lines (copy/paste):")
    print("-"*70)
    print("# Already set (example):")
    print("JIRA_FIELD_ENVIRONMENT=environment  # standard Environment field (now default)")
    print("# If you create custom fields in Jira (Project Settings -> Fields -> Create custom field -> Text/URL/User), set:")
    for display, key in REQUIRED_FIELDS:
        if key in ("assignee","reporter","environment"):
            continue
        env = LOGICAL_TO_ENV[key]
        cur = getattr(s, env, "")
        if not cur:
            print(f"{env}=customfield_XXXXX  # create '{display}' custom field and paste its ID here")
        else:
            print(f"{env}={cur}  # already mapped")
    print()
    print("Fallback behavior (no .env change needed):")
    print("  populate_jira.py now embeds a 'RAB Details' block in each issue description")
    print("  with all 10 fields. FieldValidator now parses that block when env is empty,")
    print("  so tickets will validate and dashboard will show details instead of blank.")
    print()
    print("Next step to verify:")
    print("  python scripts/populate_jira.py --project TEST --count 1 --sync")
    print("  python -c \"from app.services.field_validator import FieldValidator; fv=FieldValidator(); print(fv.field_map)\"")
    print("="*70)

async def main():
    ap = argparse.ArgumentParser(description="Audit empty RAB field mappings")
    ap.add_argument("--full", action="store_true", help="Show all Jira fields")
    ap.add_argument("--fix-env", action="store_true", help="Append missing JIRA_FIELD_ENVIRONMENT default to .env if absent")
    args = ap.parse_args()
    fields = await fetch_fields()
    if args.fix_env:
        env_path = Path(".env")
        text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if "JIRA_FIELD_ENVIRONMENT" not in text:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write("\nJIRA_FIELD_ENVIRONMENT=environment\n")
            print("Appended JIRA_FIELD_ENVIRONMENT=environment to .env")
        else:
            print("JIRA_FIELD_ENVIRONMENT already in .env")
    # Filter for full flag
    if not args.full:
        # Limit to relevant
        pass
    print_report(fields)

if __name__ == "__main__":
    asyncio.run(main())
