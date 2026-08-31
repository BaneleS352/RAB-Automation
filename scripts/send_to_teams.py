import os
import requests
from dotenv import load_dotenv

load_dotenv()

webhook_url = os.getenv("TEAMS_WORKFLOW_WEBHOOK_URL")

if not webhook_url:
    raise RuntimeError("TEAMS_WORKFLOW_WEBHOOK_URL was not found")

payload = {
    "type": "AdaptiveCard",
    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    "version": "1.2",
    "body": [
        {
            "type": "TextBlock",
            "text": "Is this your choice?",
            "size": "Medium",
            "weight": "Bolder",
            "wrap": True
        }
    ],
    "actions": [
        {
            "type": "Action.OpenUrl",
            "title": "Yes",
            "url": "https://your-api.example.com/confirm?choice=yes&request_id=123"
        },
        {
            "type": "Action.OpenUrl",
            "title": "No",
            "url": "https://your-api.example.com/confirm?choice=no&request_id=123"
        }
    ]
}

try:
    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Response body: {response.text}")

    response.raise_for_status()
    print("Card sent successfully.")

except requests.RequestException as error:
    print(f"Request failed: {error}")