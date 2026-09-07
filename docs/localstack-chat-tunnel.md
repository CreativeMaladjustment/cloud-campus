# LocalStack Chat App via Cloudflare Tunnel

This repository includes a GitHub Actions workflow that deploys a small username-only chat app — a Lambda Function URL backed by a DynamoDB table — to LocalStack, and exposes it to the public internet for twenty minutes using a Cloudflare Quick Tunnel. It builds on the same pattern as the [hello-world tunnel demo](localstack-tunnel.md), but with real application logic and persistent state instead of a static response.

The workflow is defined in `.github/workflows/localstack-chat-tunnel.yml`. The Lambda source lives in `lambda_functions/chat_app/handler.py`.

## What the app does

- **Login page** — asks for a display name only, no password. The name is stored in a cookie and shown alongside every message you post.
- **Chat page** — anyone who has entered a name can post a message and see every message anyone has left. The page auto-refreshes every few seconds. Messages persist in DynamoDB for as long as the LocalStack container is running.

There is no real authentication or authorization: this is a demo of wiring Lambda + DynamoDB + a tunnel together, not a security model. Anyone with the tunnel URL can read and post messages under any name they type.

## Triggers

This workflow only runs via `workflow_dispatch` — trigger it manually from the **Actions** tab. It does not run on push or pull request.

Like `localstack-tunnel.yml` and `test-s3-localstack.yaml`, the job declares `environment: localstack`, so each run must be approved before it starts, and it uses the environment's `LOCALSTACK_CI_TOKEN` secret (passed in as `LOCALSTACK_AUTH_TOKEN`) to run LocalStack with Pro features enabled.

## Architecture

```
Browser --(https://*.trycloudflare.com)--> cloudflared --(http://localhost:4566, Host header rewritten)--> LocalStack --> Lambda Function URL (chat-app) --> DynamoDB (chat-messages)
```

A single Lambda function, `chat-app`, renders every page server-side behind one Function URL — there is no separate static file and no client-side JavaScript at all:

| Route | Method | Behavior |
| --- | --- | --- |
| `/` | `GET` | Renders the login page (no `chat_username` cookie) or the chat page with the current messages (cookie present) |
| `/login?username=...` | `GET` | Validates the name, sets a `chat_username` cookie, redirects to `/#bottom` |
| `/send?message=...` | `GET` | Validates the message, writes it to DynamoDB as the cookie's username, redirects to `/#bottom` |
| `/logout` | `GET` | Clears the cookie, redirects to `/` |

The chat page "polls" via `<meta http-equiv="refresh" content="4;url=/#bottom">` rather than JavaScript — the browser just reloads the page every 4 seconds. The `#bottom` fragment (an anchor after the last message) keeps the view scrolled to the newest message across refreshes and after sending, without any JS.

### Why every action here is a plain GET request

Earlier versions of this app used a JSON API (`/api/messages`) called from client-side `fetch()`, with the page served as a static single-page app. That worked when tested with `curl` directly against LocalStack, but failed for every real browser request — the debug tooling built for that version (an in-page request log, since removed along with the JSON API) traced it to a bare `403 Forbidden`, with no response body and none of LocalStack's own response headers, meaning the request never reached the Lambda at all. Comparing a `curl` request without an `Origin` header (succeeded) against one with the *exact matching* `Origin` for that tunnel (still blocked) ruled out a legitimate origin-mismatch check — the block was on the mere presence of an `Origin` header.

That matches a well-documented, known-non-negotiable behavior: **Cloudflare's Bot Fight Mode**, which runs by default on the shared `trycloudflare.com` Quick Tunnel zone (this repo doesn't own that zone, so there's no dashboard to turn it off — and Cloudflare's own docs say Bot Fight Mode can't be selectively bypassed by a WAF rule regardless). It treats "API-style" requests — the kind that carry a non-empty `Origin` header, which browsers attach to `fetch()`/XHR calls and to non-GET requests generally — as automated traffic and rejects them before they reach `cloudflared` or LocalStack. Plain GET page navigations don't carry `Origin` and aren't affected, which is exactly the split observed: the page always loaded, only the API calls made from JavaScript failed.

The fix wasn't a Lambda or LocalStack config change (there wasn't one that could reach the actual cause) — it was rearchitecting the app so every interaction is a GET-driven page load or HTML form submission instead of a `fetch()` call, which is what `handler.py` and the routes above now do. `/login` and `/send` are GET requests rather than POST specifically because GET is the one request shape proven to get through; a same-origin POST form submission may still carry `Origin` under the same browser behavior that causes `fetch()` to.

Going GET-only wasn't quite the whole story, though: a real browser submitting the `/login` form still got blocked with the same bare Cloudflare error page, even though the *identical* request (`GET /login?username=...`) made with `curl` on the same tunnel, moments earlier, succeeded — the CI sanity check's own `/login` call had already gone through cleanly. The difference is `Referer`: a browser attaches it to a form-submission navigation (pointing back at the page the form was on), while `curl` never sends one unless told to, and Bot Fight Mode appears to flag that too. Every response now sends `Referrer-Policy: no-referrer` (as both an HTTP header and a `<meta name="referrer">` tag, for the widest client support), which stops the browser from attaching `Referer` to any request made from our own pages.

### DynamoDB table

`chat-messages` uses a composite key so all messages for a room can be queried in order without a table scan:

- Partition key: `room` (string) — currently always `"global"`, so the whole table is one chat room.
- Sort key: `sort_key` (string) — `<millisecond-epoch, zero-padded>#<random uuid>`, which sorts chronologically and stays unique even for messages written in the same millisecond.

Each item also stores `username`, `message`, and an ISO 8601 `created_at` timestamp.

### Talking to DynamoDB from inside the Lambda

LocalStack injects `LOCALSTACK_HOSTNAME` (and usually `EDGE_PORT`) into the Lambda execution environment so a function can call back into other local AWS services. `handler.py`'s `get_endpoint_url()` checks for that variable and, when present, points boto3 at `http://$LOCALSTACK_HOSTNAME:$EDGE_PORT`; otherwise it returns `None` so boto3 falls back to normal AWS endpoint resolution. The same handler code would work unmodified against real AWS Lambda + DynamoDB.

### XSS and cookies

All user-supplied content (usernames, messages) is rendered into HTML via Python's `html.escape()` before being interpolated into a page — there's no client-side templating to accidentally trust. The `chat_username` cookie is set with `SameSite=Lax` and URL-encoded (`urllib.parse.quote`/`unquote`) so a name containing spaces or other special characters round-trips correctly.

## What the workflow does

1. **Starts LocalStack** and waits for both the `lambda` and `dynamodb` services to report healthy.
2. **Creates the `chat-messages` DynamoDB table** with the `room` / `sort_key` composite key described above.
3. **Packages and deploys the `chat-app` Lambda** from `lambda_functions/chat_app/handler.py`, with `TABLE_NAME=chat-messages` set as an environment variable and an explicit 30-second timeout / 256 MB memory (LocalStack's Docker-based Lambda executor commonly cold-starts per invocation, which can exceed AWS's 3-second default under real traffic), and creates a public Function URL (`auth-type NONE`, with the matching `lambda:InvokeFunctionUrl` resource policy).
4. **Sanity-checks it locally** — using a `curl` cookie jar against the Function URL's own `Host` header, it exercises the full flow without the tunnel: unauthenticated `GET /` shows the login page, `GET /login?username=...` sets the cookie and redirects, authenticated `GET /` shows the chat page, `GET /send?message=...` posts a message and redirects, and a final `GET /` confirms the message shows up.
5. **Starts a Cloudflare Quick Tunnel** pointed at `http://localhost:4566` with `--http-host-header` set to the Lambda's Function URL host (see [why this flag is required](localstack-tunnel.md#why---http-host-header-is-required) — the same reasoning applies here), and prints the assigned `https://*.trycloudflare.com` URL to the job's step summary and console.
6. **Holds the tunnel open for 20 minutes** so there's time to open the link and actually chat. Once a minute it also prints any `chat-app` Lambda log events from the last minute, so errors from real browser traffic show up in the job log as they happen.
7. **Saves logs and tears down** — in `if: always()` steps (so this runs whether the job finished normally, failed, or was **cancelled**), it dumps the full `chat-app` CloudWatch log group and the LocalStack container's own logs to files, uploads them as a `chat-tunnel-logs` workflow artifact (see [Troubleshooting](#troubleshooting)), then stops `cloudflared` and removes the LocalStack container.

## Running it

1. Go to the **Actions** tab → **LocalStack Chat App via Cloudflare Tunnel** → **Run workflow**.
2. Approve the `localstack` environment deployment if prompted.
3. Once the job reaches the "Publish tunnel URL" step, the public URL is printed in the step summary and the console logs — open it in a browser, enter a display name, and start chatting. Share the same URL with anyone else you want in the conversation.
4. The page refreshes itself every 4 seconds to show new messages; there's no need to manually reload.
5. The tunnel and LocalStack are automatically torn down after the 20-minute hold, whether the run succeeded or failed — chat history is not preserved between runs.

## Troubleshooting

**The page loads, but `/api/messages` returns a `403` / "Couldn't refresh messages" / "failed to send message".**

You're likely running an older version of this workflow. That symptom belongs to a previous, JS-`fetch()`-based design and was caused by Cloudflare's Bot Fight Mode (see [why every action here is a plain GET request](#why-every-action-here-is-a-plain-get-request) above) — not something fixable with a LocalStack or Lambda config tweak. The app was rearchitected to avoid it entirely: there's no `/api/messages` endpoint anymore, no client-side JavaScript, and nothing that can trigger that specific block. Pull the latest `handler.py` and workflow.

**Something else is wrong — the login/chat page doesn't render, or sending a message silently does nothing.**

Two tools are built in specifically for diagnosing this without guessing:

1. **The `chat-tunnel-logs` workflow artifact.** Every run — whether it completes normally, fails, or is **manually cancelled** — uploads an artifact containing the full `chat-app` CloudWatch log group (`logs/chat-app-lambda.json`) and the LocalStack container's own stdout/stderr (`logs/localstack-container.log`). Find it on the workflow run's summary page under **Artifacts** once the "Save chat-app and LocalStack logs" step has run (which happens before teardown, so it's captured even if you cancel the run early). `handler.py` catches any unexpected exception and prints it via `print()` before returning a generic error page, so the real traceback shows up here.
2. **The job log during the run.** The 20-minute hold step prints any `chat-app` log events from the last minute once a minute, so you can watch them live in the Actions UI without waiting for the artifact.

If you have local AWS CLI access to a still-running LocalStack container, you can also query logs directly instead of waiting for the artifact:

```bash
awslocal logs filter-log-events --log-group-name /aws/lambda/chat-app
```

(`awslocal logs tail` is not used here since the workflow installs `awscli-local[ver1]`, and `logs tail` is an AWS CLI v2-only command — `filter-log-events` works on both.)

## Tests

`lambda_functions/chat_app/handler.py` is covered by fast unit tests in `tests/unit/test_chat_app.py`, which mock the DynamoDB table entirely (no LocalStack required) and cover request validation, cookie handling, redirect behavior, XSS escaping, and the Lambda routing logic. They run on every pull request via `.github/workflows/python-unit-tests.yaml`:

```bash
pip install -r requirements-dev.txt
pytest tests/unit -v
```
