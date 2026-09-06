"""Fast unit tests for scripts/create_s3_bucket.py.

These tests mock boto3 entirely, so they don't need a running
LocalStack instance and are safe to run on every PR.
"""
from unittest.mock import MagicMock

import boto3

from scripts.create_s3_bucket import (
    DEFAULT_BUCKET_NAME,
    DEFAULT_ENDPOINT_URL,
    DEFAULT_REGION,
    create_bucket,
    get_s3_client,
    main,
)


def test_create_bucket_default_region_omits_location_constraint():
    mock_client = MagicMock()

    create_bucket(mock_client, "some-bucket", region="us-east-1")

    mock_client.create_bucket.assert_called_once_with(Bucket="some-bucket")


def test_create_bucket_non_default_region_sets_location_constraint():
    mock_client = MagicMock()

    create_bucket(mock_client, "some-bucket", region="us-west-2")

    mock_client.create_bucket.assert_called_once_with(
        Bucket="some-bucket",
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
    )


def test_get_s3_client_uses_explicit_args(monkeypatch):
    mock_client_factory = MagicMock(return_value="the-client")
    monkeypatch.setattr(boto3, "client", mock_client_factory)

    result = get_s3_client(endpoint_url="http://example:4566", region="eu-west-1")

    assert result == "the-client"
    mock_client_factory.assert_called_once_with(
        "s3",
        endpoint_url="http://example:4566",
        region_name="eu-west-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_get_s3_client_falls_back_to_defaults(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    mock_client_factory = MagicMock()
    monkeypatch.setattr(boto3, "client", mock_client_factory)

    get_s3_client()

    mock_client_factory.assert_called_once_with(
        "s3",
        endpoint_url=DEFAULT_ENDPOINT_URL,
        region_name=DEFAULT_REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_get_s3_client_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://example-localstack:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    mock_client_factory = MagicMock()
    monkeypatch.setattr(boto3, "client", mock_client_factory)

    get_s3_client()

    mock_client_factory.assert_called_once_with(
        "s3",
        endpoint_url="http://example-localstack:4566",
        region_name="ap-southeast-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_main_uses_env_bucket_name_and_prints_summary(monkeypatch, capsys):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("BUCKET_NAME", "main-test-bucket")

    mock_s3_client = MagicMock()
    mock_s3_client.list_buckets.return_value = {
        "Buckets": [{"Name": "main-test-bucket"}]
    }
    monkeypatch.setattr(
        "scripts.create_s3_bucket.get_s3_client",
        MagicMock(return_value=mock_s3_client),
    )

    main()

    mock_s3_client.create_bucket.assert_called_once_with(Bucket="main-test-bucket")
    output = capsys.readouterr().out
    assert "Created bucket: main-test-bucket" in output
    assert "main-test-bucket" in output


def test_main_defaults_to_default_bucket_name(monkeypatch):
    monkeypatch.delenv("BUCKET_NAME", raising=False)

    mock_s3_client = MagicMock()
    mock_s3_client.list_buckets.return_value = {"Buckets": []}
    monkeypatch.setattr(
        "scripts.create_s3_bucket.get_s3_client",
        MagicMock(return_value=mock_s3_client),
    )

    main()

    mock_s3_client.create_bucket.assert_called_once_with(Bucket=DEFAULT_BUCKET_NAME)
