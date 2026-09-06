"""Integration tests for scripts/create_s3_bucket.py against a real LocalStack instance.

These tests require LocalStack to be running and reachable at
AWS_ENDPOINT_URL (default http://localhost:4566), same as the
"Create S3 bucket with boto3" CI step. Each test creates its own
disposable bucket and cleans up after itself.
"""
import uuid

import pytest

from scripts.create_s3_bucket import create_bucket, get_s3_client


@pytest.fixture(scope="module")
def s3_client():
    return get_s3_client()


@pytest.fixture
def disposable_bucket_name():
    return f"pytest-integration-{uuid.uuid4().hex[:8]}"


def test_create_bucket_creates_a_real_bucket(s3_client, disposable_bucket_name):
    create_bucket(s3_client, disposable_bucket_name, region="us-east-1")

    try:
        s3_client.head_bucket(Bucket=disposable_bucket_name)
        bucket_names = [b["Name"] for b in s3_client.list_buckets()["Buckets"]]
        assert disposable_bucket_name in bucket_names
    finally:
        s3_client.delete_bucket(Bucket=disposable_bucket_name)


def test_put_and_get_object_round_trip(s3_client, disposable_bucket_name):
    create_bucket(s3_client, disposable_bucket_name, region="us-east-1")

    try:
        s3_client.put_object(
            Bucket=disposable_bucket_name, Key="hello.txt", Body=b"hello localstack"
        )
        response = s3_client.get_object(Bucket=disposable_bucket_name, Key="hello.txt")
        assert response["Body"].read() == b"hello localstack"
    finally:
        s3_client.delete_object(Bucket=disposable_bucket_name, Key="hello.txt")
        s3_client.delete_bucket(Bucket=disposable_bucket_name)
