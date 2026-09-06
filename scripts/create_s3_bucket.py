#!/usr/bin/env python3
"""Create an S3 bucket against LocalStack using boto3.

Mirrors the CloudFormation (templates/s3-bucket.yaml) and Terraform
(templates/main.tf) examples in this repo, but using the boto3 SDK
directly against a local LocalStack endpoint.
"""
import os

import boto3

ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "my-boto3-test-bucket")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def create_bucket(s3_client, bucket_name: str):
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name)
    else:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
    print(f"Created bucket: {bucket_name}")


def main():
    s3_client = get_s3_client()
    create_bucket(s3_client, BUCKET_NAME)

    print("Current buckets:")
    for bucket in s3_client.list_buckets()["Buckets"]:
        print(f"  - {bucket['Name']}")


if __name__ == "__main__":
    main()
