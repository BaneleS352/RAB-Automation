import traceback
from fastapi.testclient import TestClient
from app.main import create_app

with TestClient(create_app(), raise_server_exceptions=False) as c:
    for scenario in ["", "pending_sdl", "pending_sdm", "validation_failed", "validated_with_notes", "rejected_sdl", "rejected_sdm", "aging"]:
        key = "REPRO-%d" % (abs(hash(scenario)) % 900 + 100)
        r = c.post("/dashboard/demo", data={"issue_key": key, "summary": "repro", "scenario": scenario, "use_real_jira": "false"})
        print(f"scenario={scenario!r:22} -> {r.status_code}")
