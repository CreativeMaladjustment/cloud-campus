"""Fast unit tests for lambda_functions/chat_app/handler.py.

These tests mock the DynamoDB table entirely, so they don't need a running
LocalStack instance and are safe to run on every PR.
"""
import json
from unittest.mock import MagicMock

import boto3
import pytest

from lambda_functions.chat_app.handler import (
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


def _http_event(method, path, body=None):
    event = {"requestContext": {"http": {"method": method, "path": path}}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


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
    assert result == {
        "username": "alice",
        "message": "hello there",
        "created_at": item["created_at"],
    }


# -- lambda_handler -------------------------------------------------------


def test_lambda_handler_get_root_serves_html(monkeypatch):
    response = lambda_handler(_http_event("GET", "/"), None)

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"].startswith("text/html")
    assert "<html" in response["body"]


def test_lambda_handler_get_messages_returns_json(monkeypatch):
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": []}
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    response = lambda_handler(_http_event("GET", "/api/messages"), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"messages": []}


def test_lambda_handler_post_messages_creates_message(monkeypatch):
    mock_table = MagicMock()
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = _http_event("POST", "/api/messages", {"username": "alice", "message": "hi"})
    response = lambda_handler(event, None)

    assert response["statusCode"] == 201
    mock_table.put_item.assert_called_once()
    body = json.loads(response["body"])
    assert body["message"]["username"] == "alice"
    assert body["message"]["message"] == "hi"


def test_lambda_handler_post_messages_rejects_missing_username(monkeypatch):
    mock_table = MagicMock()
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = _http_event("POST", "/api/messages", {"message": "hi"})
    response = lambda_handler(event, None)

    assert response["statusCode"] == 400
    mock_table.put_item.assert_not_called()


def test_lambda_handler_post_messages_rejects_invalid_json(monkeypatch):
    mock_table = MagicMock()
    monkeypatch.setattr("lambda_functions.chat_app.handler.get_table", lambda: mock_table)

    event = {
        "requestContext": {"http": {"method": "POST", "path": "/api/messages"}},
        "body": "not json",
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 400


def test_lambda_handler_unknown_api_path_returns_404():
    response = lambda_handler(_http_event("GET", "/api/nope"), None)
    assert response["statusCode"] == 404


def test_lambda_handler_post_to_root_returns_405():
    response = lambda_handler(_http_event("POST", "/"), None)
    assert response["statusCode"] == 405
