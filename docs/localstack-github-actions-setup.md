# LocalStack GitHub Actions Workflow

This project includes a GitHub Actions workflow (`.github/workflows/test-s3-localstack.yaml`) designed to test AWS CloudFormation deployments locally using LocalStack.

## What is LocalStack?

LocalStack provides a fully functional local AWS cloud stack, allowing you to develop and test your cloud and Serverless apps offline.

## Workflow Details

The workflow is triggered on pushes to the `main` branch (specifically when changes occur to the workflow itself, the `templates/s3-bucket.yaml`/`templates/main.tf` templates, the `scripts/create_s3_bucket.py` script, or `requirements.txt`) and on pull requests.

### Steps

1. **Checkout code:** Uses the standard GitHub `actions/checkout` to pull the repository into the runner.
2. **Setup Python:** Uses `actions/setup-python` to ensure Python 3.13 is available and caches Python dependencies (`pip`) based on the `requirements.txt` file.
3. **Cache LocalStack Image:** Uses `actions/cache` to cache the LocalStack Docker image across runs to speed up the workflow execution.
4. **Setup LocalStack:** Uses the official `LocalStack/setup-localstack` action. It sets up LocalStack and installs the `awslocal` CLI wrapper. It uses the `LOCALSTACK_CI_TOKEN` to authenticate pro features and the `LOCALSTACK_ACKNOWLEDGE_ACCOUNT_REQUIREMENT` environment variable to bypass the account requirement screen.
5. **Install Python dependencies:** Installs `requirements-dev.txt` (which pulls in `boto3`, `awscli-local`, and `pytest`).
6. **Deploy CloudFormation Template:** Uses the `awslocal` CLI to deploy the `templates/s3-bucket.yaml` CloudFormation template to the running LocalStack instance. The template creates a simple private S3 bucket.
7. **Deploy Terraform Template:** Uses `tflocal` to apply `templates/main.tf`, creating another bucket via Terraform.
8. **Create S3 bucket with boto3:** Runs `scripts/create_s3_bucket.py`, which uses the boto3 SDK directly to create a bucket against the same LocalStack endpoint.
9. **Run boto3 integration tests:** Runs `pytest tests/integration`, which exercises `scripts/create_s3_bucket.py` against the live LocalStack instance (creating and cleaning up its own disposable buckets, plus a put/get object round trip).
10. **Validate Deployment:** Runs AWS CLI commands via `awslocal` to list S3 buckets and confirm the buckets created by the CloudFormation, Terraform, and boto3 examples all exist.

## boto3 Example

`scripts/create_s3_bucket.py` shows how to create an S3 bucket with boto3 against a local LocalStack instance, as an alternative to the CloudFormation and Terraform examples above. It points the boto3 client at LocalStack's endpoint (`http://localhost:4566` by default) with dummy `test`/`test` credentials, then creates a bucket named `my-boto3-test-bucket`.

Run it locally (with LocalStack already running, e.g. via `localstack start`):

```bash
pip install -r requirements.txt
python scripts/create_s3_bucket.py
```

The endpoint, bucket name, and region can be overridden via the `AWS_ENDPOINT_URL`, `BUCKET_NAME`, and `AWS_DEFAULT_REGION` environment variables.

## Tests

Tests for `scripts/create_s3_bucket.py` live under `tests/` and are split into two suites:

- **`tests/unit/`** — mocks `boto3` entirely (no network calls), so it runs fast with no LocalStack required. This suite runs on every pull request via the independent `.github/workflows/python-unit-tests.yaml` check.
- **`tests/integration/`** — exercises the script against a real, running LocalStack instance (creating and tearing down its own disposable buckets). This suite runs as part of `.github/workflows/test-s3-localstack.yaml`, after LocalStack is up.

Install dev dependencies and run either suite locally with:

```bash
pip install -r requirements-dev.txt
pytest tests/unit -v          # no LocalStack needed
pytest tests/integration -v   # requires LocalStack running at AWS_ENDPOINT_URL
```

## Caching Strategy

The workflow utilizes two caching layers to improve performance:

- **Python Dependencies:** PIP caching is configured in the Python setup step.
- **Docker Images:** The LocalStack docker image (`localstack/localstack-pro:latest` or `localstack/localstack:latest`) is saved as a tarball and cached. If a cache hit occurs on the next run, the image is loaded via `docker load`, saving significant download time.
