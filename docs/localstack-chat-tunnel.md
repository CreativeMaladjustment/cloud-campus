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
6. **Holds the tunnel open for 20 minutes** so there's time to open the link and actually chat, logging progress once a minute.
7. **Tears down** — in an `if: always()` step, stops `cloudflared` and removes the LocalStack container regardless of whether earlier steps succeeded.

## Running it

1. Go to the **Actions** tab → **LocalStack Chat App via Cloudflare Tunnel** → **Run workflow**.
2. Approve the `localstack` environment deployment if prompted.
3. Once the job reaches the "Publish tunnel URL" step, the public URL is printed in the step summary and the console logs — open it in a browser, enter a display name, and start chatting. Share the same URL with anyone else you want in the conversation.
4. The tunnel and LocalStack are automatically torn down after the 20-minute hold, whether the run succeeded or failed — chat history is not preserved between runs.

## Troubleshooting

**The page loads, but the chat shows "Couldn't refresh messages. Retrying…" and sending a message flashes "failed to send message".**

This means the `chat-app` Lambda is reachable (the static page loaded fine) but is erroring on every call to `/api/messages`, for both `GET` and `POST`. The `handler.py` router only touches DynamoDB on the `/api/messages` routes — `GET /` never does — so this points at the Lambda failing (or timing out) partway through a DynamoDB call rather than a routing or tunnel problem.

The most common cause: **the Lambda invocation is too slow for its configured timeout.** LocalStack's Docker-based Lambda executor commonly cold-starts a fresh container on every invocation, and a cold Python 3.11 start plus a cross-container round trip to DynamoDB through LocalStack's gateway can easily take longer than the AWS default 3-second Lambda timeout — especially once real, repeated browser polling (rather than a single one-off `curl`) starts hitting it. A timeout comes back from the Function URL as `{"errorMessage": ..., "errorType": "..."}` (HTTP 502) rather than the app's own `{"error": "..."}` shape, which is exactly what produces the frontend's generic fallback text. The workflow deploys the Lambda with `--timeout 30 --memory-size 256` for this reason — if you've customized the deploy step and dropped those flags, add them back.

If messages still fail after that, check the actual error instead of guessing further:

```bash
awslocal logs tail /aws/lambda/chat-app --since 10m
```

`handler.py` catches any unexpected exception on the `/api/messages` routes and returns it as `{"error": "..."}` with a `500` status (rather than letting Lambda's raw error envelope leak through), and logs the real exception via `print()` so it shows up in the command above.

## Tests

`lambda_functions/chat_app/handler.py` is covered by fast unit tests in `tests/unit/test_chat_app.py`, which mock the DynamoDB table entirely (no LocalStack required) and cover request validation, message ordering, and the Lambda routing logic. They run on every pull request via `.github/workflows/python-unit-tests.yaml`:

```bash
pip install -r requirements-dev.txt
pytest tests/unit -v
```
