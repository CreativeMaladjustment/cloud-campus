# LocalStack GitHub Actions Workflow

This project includes a GitHub Actions workflow (`.github/workflows/test-s3-localstack.yaml`) designed to test AWS CloudFormation deployments locally using LocalStack.

## What is LocalStack?

LocalStack provides a fully functional local AWS cloud stack, allowing you to develop and test your cloud and Serverless apps offline.

## Workflow Details

The workflow is triggered on pushes to the `main` branch (specifically when changes occur to the workflow itself or the `templates/s3-bucket.yaml` template) and on pull requests.

### Steps

1. **Checkout code:** Uses the standard GitHub `actions/checkout` to pull the repository into the runner.
2. **Setup Python:** Uses `actions/setup-python` to ensure Python 3.13 is available and caches Python dependencies (`pip`) based on the `requirements.txt` file.
3. **Cache LocalStack Image:** Uses `actions/cache` to cache the LocalStack Docker image across runs to speed up the workflow execution.
4. **Setup LocalStack:** Uses the official `LocalStack/setup-localstack` action. It sets up LocalStack and installs the `awslocal` CLI wrapper. It uses the `LOCALSTACK_CI_TOKEN` to authenticate pro features and the `LOCALSTACK_ACKNOWLEDGE_ACCOUNT_REQUIREMENT` environment variable to bypass the account requirement screen.
5. **Deploy CloudFormation Template:** Uses the `awslocal` CLI to deploy the `templates/s3-bucket.yaml` CloudFormation template to the running LocalStack instance. The template creates a simple private S3 bucket.
6. **Validate Deployment:** Runs AWS CLI commands via `awslocal` to list S3 buckets and specifically search for the `my-localstack-test-bucket` bucket created by the CloudFormation template to ensure it exists.

## Caching Strategy

The workflow utilizes two caching layers to improve performance:

- **Python Dependencies:** PIP caching is configured in the Python setup step.
- **Docker Images:** The LocalStack docker image (`localstack/localstack-pro:latest` or `localstack/localstack:latest`) is saved as a tarball and cached. If a cache hit occurs on the next run, the image is loaded via `docker load`, saving significant download time.
