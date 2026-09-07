"""Fast unit tests for lambda_functions/chat_app/handler.py.

These tests mock the DynamoDB table entirely, so they don't need a running
LocalStack instance and are safe to run on every PR.
"""
from unittest.mock import MagicMock
from urllib.parse import unquote

import boto3
import pytest

from lambda_functions.chat_app.handler import (
    COOKIE_NAME,
    DEFAULT_TABLE_NAME,
    ValidationError,
    get_endpoint_url,
    get_table,
    lambda_handler,
    list_messages,
    post_message,
    validate_message,
    validate_username,
)


def _event(method, path, query=None, cookies=None):
    event = {
        "requestContext": {"http": {"method": method, "path": path}},
        "queryStringParameters": query,
    }
    if cookies:
        event["cookies"] = cookies
    return event


def _login_cookie(username):
    return f"{COOKIE_NAME}={username}"


# -- validation ---------------------------------------------------------


def test_validate_username_strips_whitespace():
    assert validate_username("  alice  ") == "alice"


def test_validate_username_rejects_empty():
    with pytest.raises(ValidationError):
        validate_username("   ")


def test_validate_username_rejects_too_long():
    with pytest.raises(ValidationError):
        validate_username("x" * 33)


def test_validate_message_rejects_empty():
    with pytest.raises(ValidationError):
        validate_message("")


def test_validate_message_rejects_too_long():
    with pytest.raises(ValidationError):
        validate_message("x" * 501)


# -- get_endpoint_url / get_table ---------------------------------------


def test_get_endpoint_url_none_outside_localstack(monkeypatch):
    monkeypatch.delenv("LOCALSTACK_HOSTNAME", raising=False)
    assert get_endpoint_url() is None


def test_get_endpoint_url_uses_localstack_hostname(monkeypatch):
    monkeypatch.setenv("LOCALSTACK_HOSTNAME", "localstack")
    monkeypatch.setenv("EDGE_PORT", "4566")
    assert get_endpoint_url() == "http://localstack:4566"


def test_get_table_uses_env_table_name(monkeypatch):
    monkeypatch.delenv("LOCALSTACK_HOSTNAME", raising=False)
    monkeypatch.setenv("TABLE_NAME", "my-table")
    mock_table = MagicMock()
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    monkeypatch.setattr(boto3, "resource", MagicMock(return_value=mock_resource))

    result = get_table()

    mock_resource.Table.assert_called_once_with("my-table")
    assert result is mock_table


def test_get_table_defaults_table_name(monkeypatch):
    monkeypatch.delenv("TABLE_NAME", raising=False)
    mock_resource = MagicMock()
    monkeypatch.setattr(boto3, "resource", MagicMock(return_value=mock_resource))

    get_table()

    mock_resource.Table.assert_called_once_with(DEFAULT_TABLE_NAME)


# -- list_messages / post_message ----------------------------------------


def test_list_messages_returns_oldest_first():
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [
            {"username": "bob", "message": "second", "created_at": "t2"},
            {"username": "alice", "message": "first", "created_at": "t1"},
        ]
    }

    result = list_messages(mock_table)

    assert result == [
        {"username": "alice", "message": "first", "created_at": "t1"},
        {"username": "bob", "message": "second", "created_at": "t2"},
    ]
    assert mock_table.query.call_args.kwargs["ScanIndexForward"] is False


def test_post_message_writes_expected_item():
    mock_table = MagicMock()

    result = post_message(mock_table, "alice", "hello there")

    put_item_kwargs = mock_table.put_item.call_args.kwargs
    item = put_item_kwargs["Item"]
    assert item["room"] == "global"
    assert item["username"] == "alice"
    assert item["message"] == "hello there"
    assert "sort_key" in item and "created_at" in item


# -- lambda_handler: GET / --------------------------------------------------


def test_root_without_cookie_shows_login_page():
    response = lambda_handler(_event("GET", "/"), None)

    assert response["statusCode"] == 200
    assert "Join the chat" in response["body"]
    assert "Set-Cookie" not in response["headers"]


def test_html_responses_set_no_referrer_policy():
    # Cloudflare's Bot Fight Mode on the shared trycloudflare.com Quick
    # Tunnel zone blocks a browser's Referer-carrying form-submission GET
    # to /login even though the identical request without Referer (e.g.
    # plain curl) succeeds - suppressing Referer on outgoing requests from
    # our own pages avoids tripping it.
    response = lambda_handler(_event("GET", "/"), None)
    assert response["headers"]["Referrer-Policy"] == "no-referrer"
    assert '<meta name="referrer" content="no-referrer">' in response["body"]


def test_redirects_set_no_referrer_policy():
    response = lambda_handler(_event("GET", "/login", query={"username": "alice"}), None)
    assert response["headers"]["Referrer-Policy"] == "no-referrer"


def test_root_with_cookie_shows_chat_page(monkeypatch):
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [{"username": "alice", "message": "hi there", "created_at": "t1"}]
    }
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    response = lambda_handler(_event("GET", "/", cookies=[_login_cookie("alice")]), None)

    assert response["statusCode"] == 200
    assert "hi there" in response["body"]
    assert "— alice" in response["body"]


def test_root_escapes_message_content_to_prevent_xss(monkeypatch):
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [{"username": "<script>alert(1)</script>", "message": "<b>hi</b>", "created_at": "t1"}]
    }
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    response = lambda_handler(_event("GET", "/", cookies=[_login_cookie("alice")]), None)

    assert "<script>alert(1)</script>" not in response["body"]
    assert "&lt;script&gt;" in response["body"]


def test_root_shows_error_query_param():
    response = lambda_handler(_event("GET", "/", query={"error": "message is required"}), None)
    assert "message is required" in response["body"]


def test_root_reads_cookie_from_raw_cookie_header(monkeypatch):
    # LocalStack doesn't reliably populate the split "cookies" list Lambda
    # Function URLs provide on real AWS, so get_cookie() must also handle a
    # plain "Cookie" request header (as curl's cookie jar sends).
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": []}
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = {
        "requestContext": {"http": {"method": "GET", "path": "/"}},
        "queryStringParameters": None,
        "headers": {"cookie": f"other=1; {COOKIE_NAME}=alice; another=2"},
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert "— alice" in response["body"]


# -- lambda_handler: GET /login ----------------------------------------------


def test_login_sets_cookie_and_redirects():
    response = lambda_handler(_event("GET", "/login", query={"username": "alice"}), None)

    assert response["statusCode"] == 302
    assert response["headers"]["Location"] == "/#bottom"
    assert response["headers"]["Set-Cookie"] == f"{COOKIE_NAME}=alice; Path=/; Max-Age=86400; SameSite=Lax"


def test_login_url_encodes_username_with_special_characters():
    response = lambda_handler(_event("GET", "/login", query={"username": "a b"}), None)
    cookie_value = response["headers"]["Set-Cookie"].split(";")[0]
    assert unquote(cookie_value.split("=", 1)[1]) == "a b"


def test_login_rejects_missing_username():
    response = lambda_handler(_event("GET", "/login", query={}), None)

    assert response["statusCode"] == 400
    assert "Set-Cookie" not in response["headers"]
    assert "username is required" in response["body"]


# -- lambda_handler: GET /send -----------------------------------------------


def test_send_without_cookie_redirects_to_login():
    response = lambda_handler(_event("GET", "/send", query={"message": "hi"}), None)

    assert response["statusCode"] == 302
    assert response["headers"]["Location"] == "/"


def test_send_creates_message_and_redirects(monkeypatch):
    mock_table = MagicMock()
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = _event("GET", "/send", query={"message": "hi"}, cookies=[_login_cookie("alice")])
    response = lambda_handler(event, None)

    assert response["statusCode"] == 302
    assert response["headers"]["Location"] == "/#bottom"
    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["username"] == "alice"
    assert item["message"] == "hi"


def test_send_rejects_empty_message(monkeypatch):
    mock_table = MagicMock()
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = _event("GET", "/send", query={"message": "  "}, cookies=[_login_cookie("alice")])
    response = lambda_handler(event, None)

    assert response["statusCode"] == 302
    assert response["headers"]["Location"].startswith("/?error=")
    mock_table.put_item.assert_not_called()


# -- lambda_handler: GET /logout ---------------------------------------------


def test_logout_clears_cookie_and_redirects():
    response = lambda_handler(_event("GET", "/logout", cookies=[_login_cookie("alice")]), None)

    assert response["statusCode"] == 302
    assert response["headers"]["Location"] == "/"
    assert response["headers"]["Set-Cookie"] == f"{COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax"


# -- lambda_handler: misc -----------------------------------------------------


def test_unknown_path_returns_404():
    response = lambda_handler(_event("GET", "/nope"), None)
    assert response["statusCode"] == 404


def test_non_get_method_returns_405():
    response = lambda_handler(_event("POST", "/"), None)
    assert response["statusCode"] == 405


def test_unexpected_error_returns_error_page(monkeypatch):
    def boom():
        raise RuntimeError("dynamodb is unreachable")

    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", boom)

    response = lambda_handler(_event("GET", "/", cookies=[_login_cookie("alice")]), None)

    assert response["statusCode"] == 500
    assert "Something went wrong" in response["body"]
