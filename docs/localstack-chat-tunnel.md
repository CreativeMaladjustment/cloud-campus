# LocalStack Chat App via Cloudflare Tunnel

This repository includes a GitHub Actions workflow that deploys a small username-only chat app — a Lambda Function URL backed by a DynamoDB table — to LocalStack, and exposes it to the public internet for twenty minutes using a Cloudflare Quick Tunnel. It builds on the same pattern as the [hello-world tunnel demo](localstack-tunnel.md), but with real application logic and persistent state instead of a static response.

The workflow is defined in `.github/workflows/localstack-chat-tunnel.yml`. The Lambda source lives in `lambda_functions/chat_app/`.

## What the app does

- **Login page** — asks for a display name only, no password. The name is saved in the browser's `localStorage` and sent along with every message.
- **Chat page** — anyone who has entered a name can post a message and see every message anyone has left, polled every few seconds. Messages persist in DynamoDB for as long as the LocalStack container is running.

There is no real authentication or authorization: this is a demo of wiring Lambda + DynamoDB + a tunnel together, not a security model. Anyone with the tunnel URL can read and post messages under any name they type.

## Triggers

This workflow only runs via `workflow_dispatch` — trigger it manually from the **Actions** tab. It does not run on push or pull request.

Like `localstack-tunnel.yml` and `test-s3-localstack.yaml`, the job declares `environment: localstack`, so each run must be approved before it starts, and it uses the environment's `LOCALSTACK_CI_TOKEN` secret (passed in as `LOCALSTACK_AUTH_TOKEN`) to run LocalStack with Pro features enabled.

## Architecture

```
Browser --(https://*.trycloudflare.com)--> cloudflared --(http://localhost:4566, Host header rewritten)--> LocalStack --> Lambda Function URL (chat-app) --> DynamoDB (chat-messages)
```

A single Lambda function, `chat-app`, handles everything behind one Function URL:

| Route | Method | Behavior |
| --- | --- | --- |
| `/` (and any other non-API path) | `GET` | Serves the single-page chat UI (`lambda_functions/chat_app/static/index.html`) |
| `/api/messages` | `GET` | Returns the most recent messages as JSON, oldest first |
| `/api/messages` | `POST` | Validates `{"username", "message"}` and writes a new message |

The front end is a single static HTML file with inline CSS/JS and no external dependencies. It toggles between the login view and the chat view based on whether a username is stored in `localStorage`, and polls `/api/messages` every 3 seconds while the chat view is open.

**Built-in debug log.** Click **Show debug log** in the chat header (or load the page with `?debug=1` in the URL) to reveal a panel below the message box that records every `/api/messages` request as it happens: method, HTTP status, and a truncated response body — or the exact error message when the browser's `fetch()` call fails outright (e.g. a network-level failure, distinct from an HTTP error response). This is the fastest way to see exactly what's failing without opening browser devtools; the toggle state is remembered in `localStorage`.

### DynamoDB table

`chat-messages` uses a composite key so all messages for a room can be queried in order without a table scan:

- Partition key: `room` (string) — currently always `"global"`, so the whole table is one chat room.
- Sort key: `sort_key` (string) — `<millisecond-epoch, zero-padded>#<random uuid>`, which sorts chronologically and stays unique even for messages written in the same millisecond.

Each item also stores `username`, `message`, and an ISO 8601 `created_at` timestamp.

### Talking to DynamoDB from inside the Lambda

LocalStack injects `LOCALSTACK_HOSTNAME` (and usually `EDGE_PORT`) into the Lambda execution environment so a function can call back into other local AWS services. `lambda_functions/chat_app/handler.py`'s `get_endpoint_url()` checks for that variable and, when present, points boto3 at `http://$LOCALSTACK_HOSTNAME:$EDGE_PORT`; otherwise it returns `None` so boto3 falls back to normal AWS endpoint resolution. The same handler code would work unmodified against real AWS Lambda + DynamoDB.

## What the workflow does

1. **Starts LocalStack** and waits for both the `lambda` and `dynamodb` services to report healthy.
2. **Creates the `chat-messages` DynamoDB table** with the `room` / `sort_key` composite key described above.
3. **Packages and deploys the `chat-app` Lambda** from `lambda_functions/chat_app/` (`handler.py` plus the `static/` directory), with `TABLE_NAME=chat-messages` set as an environment variable and an explicit 30-second timeout / 256 MB memory (see [Troubleshooting](#troubleshooting) below for why the Lambda default of 3 seconds isn't enough here), and creates a public Function URL (`auth-type NONE`, with the matching `lambda:InvokeFunctionUrl` resource policy).
4. **Sanity-checks it locally** — curls the function directly on the runner with the Function URL's own `Host` header, checking both the HTML page and the (empty) messages API, before troubleshooting would require going through the tunnel.
5. **Starts a Cloudflare Quick Tunnel** pointed at `http://localhost:4566` with `--http-host-header` set to the Lambda's Function URL host (see [why this flag is required](localstack-tunnel.md#why---http-host-header-is-required) — the same reasoning applies here), and prints the assigned `https://*.trycloudflare.com` URL to the job's step summary and console.
6. **Holds the tunnel open for 20 minutes** so there's time to open the link and actually chat. Once a minute it also prints any `chat-app` Lambda log events from the last minute, so errors from real browser traffic show up in the job log as they happen.
7. **Saves logs and tears down** — in `if: always()` steps (so this runs whether the job finished normally, failed, or was **cancelled**), it dumps the full `chat-app` CloudWatch log group and the LocalStack container's own logs to files, uploads them as a `chat-tunnel-logs` workflow artifact (see [Troubleshooting](#troubleshooting)), then stops `cloudflared` and removes the LocalStack container.

## Running it

1. Go to the **Actions** tab → **LocalStack Chat App via Cloudflare Tunnel** → **Run workflow**.
2. Approve the `localstack` environment deployment if prompted.
3. Once the job reaches the "Publish tunnel URL" step, the public URL is printed in the step summary and the console logs — open it in a browser, enter a display name, and start chatting. Share the same URL with anyone else you want in the conversation.
4. The tunnel and LocalStack are automatically torn down after the 20-minute hold, whether the run succeeded or failed — chat history is not preserved between runs.

## Troubleshooting

**The page loads, but the chat shows "Couldn't refresh messages. Retrying…" and sending a message fails.**

This means the `chat-app` Lambda is reachable (the static page loaded fine) but is erroring, timing out, or otherwise not returning a normal response on `/api/messages` calls. The `handler.py` router only touches DynamoDB on the `/api/messages` routes — `GET /` never does — so this points at something going wrong specifically around that Lambda invocation or DynamoDB call, not a routing or tunnel-setup problem.

Two tools are built in specifically for diagnosing this without guessing:

1. **The in-page debug log.** Click **Show debug log** in the chat header (or open the tunnel URL with `?debug=1`). It shows, for every request, the exact HTTP status and response body returned — or, distinctly, the browser's own error if `fetch()` failed before getting a response at all (e.g. a connection-level failure). This tells you immediately whether the Lambda is responding with an error (and what it says) versus the request never completing.
   - A `500` with `{"error": "internal error, check the chat-app Lambda logs"}` means `handler.py` caught an unexpected Python exception — see the workflow logs below for the real traceback.
   - A response that isn't valid JSON, or a status with no recognizable body, usually means the error came from *outside* the app (LocalStack's gateway, the Lambda runtime killing the invocation on a timeout, or the Cloudflare tunnel itself) rather than from `handler.py`'s own code.
2. **The `chat-tunnel-logs` workflow artifact.** Every run — whether it completes normally, fails, or is **manually cancelled** — uploads an artifact containing the full `chat-app` CloudWatch log group (`logs/chat-app-lambda.json`) and the LocalStack container's own stdout/stderr (`logs/localstack-container.log`). Find it on the workflow run's summary page under **Artifacts** once the "Save chat-app and LocalStack logs" step has run (which happens before teardown, so it's captured even if you cancel the run early). The run's job log also prints any `chat-app` log events once a minute during the 20-minute hold, so you can watch them live in the Actions UI without waiting for the artifact.

One cause already ruled out: an under-provisioned Lambda. The deploy step originally used AWS's default 3-second timeout, which is tight for LocalStack's Docker-based Lambda executor (it commonly cold-starts a fresh container per invocation, and a cold Python start plus a cross-container DynamoDB round trip can exceed 3s under real, repeated traffic). The workflow now deploys with `--timeout 30 --memory-size 256` — if messages still fail with that in place, the debug log and artifact above are the next step, not another timeout bump.

If you have local AWS CLI access to a still-running LocalStack container, you can also query logs directly instead of waiting for the artifact:

```bash
awslocal logs filter-log-events --log-group-name /aws/lambda/chat-app
```

(`awslocal logs tail` is not used here since the workflow installs `awscli-local[ver1]`, and `logs tail` is an AWS CLI v2-only command — `filter-log-events` works on both.)

## Tests

`lambda_functions/chat_app/handler.py` is covered by fast unit tests in `tests/unit/test_chat_app.py`, which mock the DynamoDB table entirely (no LocalStack required) and cover request validation, message ordering, and the Lambda routing logic. They run on every pull request via `.github/workflows/python-unit-tests.yaml`:

```bash
pip install -r requirements-dev.txt
pytest tests/unit -v
```
