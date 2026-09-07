"""Lambda handler for a tiny username-only chat app, backed by DynamoDB.

Deployed by .github/workflows/localstack-chat-tunnel.yml as a single Lambda
Function URL: it serves the chat page for any plain GET, and a small JSON
API under /api/messages for reading and posting chat messages. There's no
authentication beyond picking a display name - anyone who knows the tunnel
URL can read and post messages.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3

DEFAULT_TABLE_NAME = "chat-messages"
DEFAULT_REGION = "us-east-1"
ROOM = "global"
MAX_USERNAME_LENGTH = 32
MAX_MESSAGE_LENGTH = 500
MESSAGE_HISTORY_LIMIT = 50

_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()


class ValidationError(Exception):
    """Raised when a request body fails validation."""


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
    return {"username": username, "message": message, "created_at": item["created_at"]}


def _parse_json_body(event):
    raw_body = event.get("body") or "{}"
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValidationError("request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ValidationError("request body must be a JSON object")
    return body


def _json_response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _html_response(html, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": html,
    }


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    path = http.get("path") or "/"

    try:
        if path == "/api/messages" and method == "GET":
            return _json_response(200, {"messages": list_messages(get_table())})

        if path == "/api/messages" and method == "POST":
            body = _parse_json_body(event)
            username = validate_username(body.get("username"))
            message = validate_message(body.get("message"))
            created = post_message(get_table(), username, message)
            return _json_response(201, {"message": created})
    except ValidationError as exc:
        return _json_response(400, {"error": str(exc)})

    if path.startswith("/api/"):
        return _json_response(404, {"error": "not found"})

    if method == "GET":
        return _html_response(_INDEX_HTML)

    return _json_response(405, {"error": "method not allowed"})
