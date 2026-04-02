# SKILL: aihawk-trigger

## Description
This skill allows OpenClaw to trigger the AIHawk job application bot. It communicates with a local Flask webhook server to initiate the search and application process on LinkedIn.

## Trigger Phrase Examples
- "apply for AI Backend jobs in London"
- "start applying for jobs"
- "run AIHawk"
- "find me Python Developer roles in Berlin"

## Action (Webhook Request)
- **Method**: POST
- **Endpoint**: http://127.0.0.1:5050/apply
- **Headers**:
    - `x-aihawk-secret`: (Value from environment variable `AIHAWK_SECRET`)
- **JSON Body**:
    ```json
    {
      "positions": ["<extracted_role_or_position>"],
      "locations": ["<extracted_location>"],
      "max_jobs": 30
    }
    ```

## Outcome
- **Response**: OpenClaw confirms that the process has started.
- **Notification**: Once AIHawk finishes, the webhook server will send a summary (applied/failed/skipped) back to the OpenClaw notification hook.

## Setup Requirements
1. The `webhook_server.py` must be running locally (`python webhook_server.py`).
2. The environment variables `AIHAWK_SECRET`, `OPENCLAW_WEBHOOK_URL`, and `OPENCLAW_TOKEN` must be correctly configured.
