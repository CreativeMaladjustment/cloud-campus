"""Lambda handler for a tiny username-only chat app, backed by DynamoDB.

Deployed by .github/workflows/localstack-chat-tunnel.yml as a single Lambda
Function URL. There's no authentication beyond picking a display name -
anyone who knows the tunnel URL can read and post messages.

Every page here is rendered server-side, and every action (logging in,
sending a message, refreshing the list, logging out) is a plain GET request
- a top-level page load or an HTML form submission - rather than a
JavaScript fetch()/XHR call. That's deliberate: Cloudflare's Bot Fight Mode,
which runs by default on the free trycloudflare.com Quick Tunnel domain this
app is deployed behind and can't be disabled from here, blocks any request
carrying a non-empty Origin header with a bare 403 before it ever reaches
this Lambda. Browsers attach Origin to fetch()/XHR calls but not to ordinary
GET navigations, so staying GET-only and link/form-driven is what keeps this
app reachable behind the tunnel. The chat page "polls" via a <meta
http-equiv="refresh"> tag instead of JavaScript.
"""
import html
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlencode

import boto3

DEFAULT_TABLE_NAME = "chat-messages"
DEFAULT_REGION = "us-east-1"
ROOM = "global"
MAX_USERNAME_LENGTH = 32
MAX_MESSAGE_LENGTH = 500
MESSAGE_HISTORY_LIMIT = 50
COOKIE_NAME = "chat_username"
LOGIN_COOKIE_MAX_AGE = 60 * 60 * 24
REFRESH_SECONDS = 4
CHAT_URL = "/#bottom"


class ValidationError(Exception):
    """Raised when user-supplied input fails validation."""


def get_endpoint_url():
    """Point boto3 back at LocalStack when running inside it.

    LocalStack injects LOCALSTACK_HOSTNAME (and usually EDGE_PORT) into the
    Lambda execution environment so functions can call other local AWS
    services. When those aren't set (e.g. real AWS, or running tests) this
    returns None and boto3 falls back to its normal endpoint resolution.
    """
    host = os.environ.get("LOCALSTACK_HOSTNAME")
    if not host:
        return None
    port = os.environ.get("EDGE_PORT", "4566")
    return f"http://{host}:{port}"


def get_table():
    resource = boto3.resource(
        "dynamodb",
        endpoint_url=get_endpoint_url(),
        region_name=os.environ.get("AWS_REGION", DEFAULT_REGION),
    )
    return resource.Table(os.environ.get("TABLE_NAME", DEFAULT_TABLE_NAME))


def validate_username(raw_username):
    username = (raw_username or "").strip()
    if not username:
        raise ValidationError("username is required")
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValidationError(f"username must be at most {MAX_USERNAME_LENGTH} characters")
    return username


def validate_message(raw_message):
    message = (raw_message or "").strip()
    if not message:
        raise ValidationError("message is required")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValidationError(f"message must be at most {MAX_MESSAGE_LENGTH} characters")
    return message


def list_messages(table, room=ROOM, limit=MESSAGE_HISTORY_LIMIT):
    response = table.query(
        KeyConditionExpression="#room = :room",
        ExpressionAttributeNames={"#room": "room"},
        ExpressionAttributeValues={":room": room},
        ScanIndexForward=False,
        Limit=limit,
    )
    items = list(response.get("Items", []))
    items.reverse()  # oldest first, so the chat reads top-to-bottom
    return [
        {
            "username": item["username"],
            "message": item["message"],
            "created_at": item["created_at"],
        }
        for item in items
    ]


def post_message(table, username, message, room=ROOM):
    now = datetime.now(timezone.utc)
    sort_key = f"{int(now.timestamp() * 1000):020d}#{uuid.uuid4().hex}"
    item = {
        "room": room,
        "sort_key": sort_key,
        "username": username,
        "message": message,
        "created_at": now.isoformat(),
    }
    table.put_item(Item=item)
    return item


# -- cookies ----------------------------------------------------------------


def get_cookie(event, name):
    # Prefer the split "cookies" list Lambda Function URLs populate on real
    # AWS, but fall back to parsing a raw Cookie request header - LocalStack
    # doesn't reliably surface the split form.
    for cookie in event.get("cookies") or []:
        key, _, value = cookie.partition("=")
        if key.strip() == name:
            return unquote(value)

    headers = event.get("headers") or {}
    raw_cookie_header = headers.get("cookie") or headers.get("Cookie") or ""
    for part in raw_cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return unquote(value)
    return None


def cookie_header(name, value, max_age):
    return f"{name}={quote(value)}; Path=/; Max-Age={max_age}; SameSite=Lax"


# -- HTML rendering -----------------------------------------------------------

PAGE_STYLE = """
  :root {
    color-scheme: light dark;
    --bg: #0f172a;
    --panel: #1e293b;
    --panel-alt: #273449;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-text: #04263b;
    --border: #334155;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  #login-screen {
    width: 100%;
    max-width: 360px;
    padding: 2rem;
  }
  #login-screen h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
  #login-screen p { color: var(--muted); margin: 0 0 1.5rem; font-size: 0.9rem; }
  #login-form { display: flex; flex-direction: column; gap: 0.75rem; }
  .field-error { color: #fca5a5; font-size: 0.85rem; min-height: 1.1em; }
  input, button { font: inherit; color: inherit; }
  input[type="text"] {
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.65rem 0.75rem;
  }
  input[type="text"]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  button {
    background: var(--accent);
    color: var(--accent-text);
    border: none;
    border-radius: 8px;
    padding: 0.65rem 0.9rem;
    font-weight: 600;
    cursor: pointer;
  }
  #chat-screen {
    width: 100%;
    max-width: 560px;
    height: min(80vh, 720px);
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  #chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.9rem 1.1rem;
    border-bottom: 1px solid var(--border);
  }
  #chat-header h1 { font-size: 1rem; margin: 0; }
  #chat-header .who { color: var(--muted); font-weight: 400; }
  #logout-button {
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.4rem 0.7rem;
    font-weight: 500;
    font-size: 0.85rem;
    text-decoration: none;
  }
  #messages { flex: 1; overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: 0.6rem; }
  #messages .empty { color: var(--muted); text-align: center; margin-top: 2rem; font-size: 0.9rem; }
  .message { max-width: 80%; padding: 0.5rem 0.7rem; border-radius: 10px; background: var(--panel-alt); align-self: flex-start; }
  .message.own { align-self: flex-end; background: var(--accent); color: var(--accent-text); }
  .message .meta { display: block; font-size: 0.72rem; opacity: 0.75; margin-bottom: 0.15rem; }
  .message .text { white-space: pre-wrap; word-break: break-word; }
  #compose { display: flex; gap: 0.5rem; padding: 0.75rem; border-top: 1px solid var(--border); }
  #compose input[type="text"] { flex: 1; }
  #chat-error { color: #fca5a5; font-size: 0.8rem; padding: 0 0.75rem 0.5rem; min-height: 1em; }
  #chat-actions { padding: 0 0.75rem 0.75rem; text-align: center; }
  #check-button {
    display: inline-block;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.4rem 0.9rem;
    font-size: 0.8rem;
    text-decoration: none;
  }
"""


def render_page(title, body_html, head_extra=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
{head_extra}
<title>{html.escape(title)}</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def render_login_page(error=None):
    error_html = html.escape(error) if error else ""
    body = f"""
<main id="login-screen">
  <h1>Join the chat</h1>
  <p>Pick a display name. No password — anyone with the link can read and post messages.</p>
  <form id="login-form" method="GET" action="/login">
    <input type="text" name="username" placeholder="Your name" maxlength="{MAX_USERNAME_LENGTH}" autocomplete="off" autofocus required>
    <button type="submit">Join chat</button>
    <div class="field-error">{error_html}</div>
  </form>
</main>
"""
    return render_page("LocalStack Chat", body)


def render_chat_page(username, messages, error=None):
    error_html = html.escape(error) if error else ""
    if messages:
        bubbles = []
        for item in messages:
            own = " own" if item["username"] == username else ""
            bubbles.append(
                f'<div class="message{own}">'
                f'<span class="meta">{html.escape(item["username"])}</span>'
                f'<span class="text">{html.escape(item["message"])}</span>'
                f"</div>"
            )
        messages_html = "".join(bubbles) + '<a id="bottom"></a>'
    else:
        messages_html = '<div class="empty">No messages yet — say hello.</div><a id="bottom"></a>'

    body = f"""
<main id="chat-screen">
  <div id="chat-header">
    <h1>Chat <span class="who">— {html.escape(username)}</span></h1>
    <a id="logout-button" href="/logout">Log out</a>
  </div>
  <div id="messages">{messages_html}</div>
  <div id="chat-error">{error_html}</div>
  <form id="compose" method="GET" action="/send">
    <input type="text" name="message" placeholder="Type a message" maxlength="{MAX_MESSAGE_LENGTH}" autocomplete="off" autofocus required>
    <button type="submit">Send</button>
  </form>
  <div id="chat-actions">
    <a id="check-button" href="/">Check for new messages</a>
  </div>
</main>
"""
    # Refreshing to /#bottom (rather than plain /) keeps the view scrolled to
    # the newest message on every auto-refresh, without any JavaScript.
    head_extra = f'<meta http-equiv="refresh" content="{REFRESH_SECONDS};url={CHAT_URL}">'
    return render_page("LocalStack Chat", body, head_extra=head_extra)


def render_error_page():
    body = """
<main id="login-screen">
  <h1>Something went wrong</h1>
  <p>Check the chat-app Lambda logs for details.</p>
</main>
"""
    return render_page("LocalStack Chat — Error", body)


# -- responses ----------------------------------------------------------------


def _html_response(body, status_code=200):
    return {
        "statusCode": status_code,
        # Referrer-Policy: no-referrer stops the browser from sending a
        # Referer header on the next navigation or form submission made from
        # this page. Cloudflare's Bot Fight Mode on the shared
        # trycloudflare.com Quick Tunnel zone appears to flag requests
        # carrying one - a form-submission GET to /login from a real browser
        # got blocked with a bare 403 even though curl making the exact same
        # request (no Referer) succeeded on the same tunnel moments earlier.
        "headers": {"Content-Type": "text/html; charset=utf-8", "Referrer-Policy": "no-referrer"},
        "body": body,
    }


def _redirect(location, cookie=None):
    headers = {"Location": location, "Referrer-Policy": "no-referrer"}
    if cookie:
        # A real Set-Cookie header, not the Lambda Function URL "cookies"
        # response field - LocalStack doesn't reliably turn that into an
        # actual Set-Cookie header on the wire, so a client's cookie jar
        # never sees it and every "logged in" request looks unauthenticated.
        headers["Set-Cookie"] = cookie
    return {"statusCode": 302, "headers": headers, "body": ""}


def _redirect_to_chat_with_error(message):
    return _redirect("/?" + urlencode({"error": message}))


# -- routing --------------------------------------------------------------------


def _route(event):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    path = http.get("path") or "/"
    query = event.get("queryStringParameters") or {}
    username = get_cookie(event, COOKIE_NAME)

    if method != "GET":
        return _html_response(render_login_page(), status_code=405)

    if path == "/login":
        try:
            new_username = validate_username(query.get("username"))
        except ValidationError as exc:
            return _html_response(render_login_page(error=str(exc)), status_code=400)
        return _redirect(CHAT_URL, cookie_header(COOKIE_NAME, new_username, LOGIN_COOKIE_MAX_AGE))

    if path == "/logout":
        return _redirect("/", cookie_header(COOKIE_NAME, "", 0))

    if path == "/send":
        if not username:
            return _redirect("/")
        try:
            message = validate_message(query.get("message"))
        except ValidationError as exc:
            return _redirect_to_chat_with_error(str(exc))
        post_message(get_table(), username, message)
        return _redirect(CHAT_URL)

    if path == "/":
        if not username:
            return _html_response(render_login_page(error=query.get("error")))
        messages = list_messages(get_table())
        return _html_response(render_chat_page(username, messages, error=query.get("error")))

    return _html_response(render_login_page(), status_code=404)


def lambda_handler(event, context):
    try:
        return _route(event)
    except Exception as exc:  # surface a real error page instead of Lambda's raw error envelope
        print(f"Unhandled error: {exc!r}")
        return _html_response(render_error_page(), status_code=500)
