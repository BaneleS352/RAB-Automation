import os

statuses = set()
targets = [
    "pending", "validated", "validation_failed",
    "sdl_requested", "sdl_approved", "sdl_rejected",
    "sdm_requested", "sdm_approved", "sdm_rejected",
    "release_ready", "meeting_scheduled",
]

for root, dirs, files in os.walk("app"):
    for fname in files:
        if not fname.endswith(".py"):
            continue
        path = os.path.join(root, fname)
        with open(path) as fh:
            for line in fh:
                for s in targets:
                    if f'"{s}"' in line or "'{s}'" in line:
                        statuses.add(s)
                        break

print("Statuses found:")
for s in sorted(statuses):
    print(f"  {s}")