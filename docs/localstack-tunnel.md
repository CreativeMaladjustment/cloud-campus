# LocalStack Cloudflare Tunnel Demo

This repository includes a GitHub Actions workflow that deploys a Lambda function to LocalStack and exposes it to the public internet for ten minutes using a Cloudflare Quick Tunnel — a way to demo a LocalStack-hosted Lambda Function URL from outside the runner without deploying anything to real AWS.

The workflow is defined in `.github/workflows/localstack-tunnel.yml`.

## Triggers

This workflow only runs via `workflow_dispatch` — trigger it manually from the **Actions** tab. It does not run on push or pull request.

Because the job declares `environment: localstack` (the same environment `test-s3-localstack.yaml` uses), each run must be approved before it starts, the same way the other LocalStack workflow is gated. The environment also holds the `LOCALSTACK_CI_TOKEN` secret, passed into the container as `LOCALSTACK_AUTH_TOKEN` so LocalStack runs with Pro features enabled.

## What it does

1. **Starts LocalStack** — runs `localstack/localstack:latest` with `/var/run/docker.sock` mounted, which LocalStack needs to spin up the sibling containers that actually execute Lambda invocations. Polls `http://localhost:4566/_localstack/health` until the `lambda` service reports ready.
2. **Deploys a Lambda** — installs `awscli-local`, packages a minimal Python 3.11 function named `hello-world` that returns `<h1>Hello from LocalStack via Cloudflare Tunnel!</h1>` (`Content-Type: text/html`), and creates a public Function URL (`auth-type NONE`, with the matching `lambda:InvokeFunctionUrl` resource policy so anonymous requests are allowed).
3. **Sanity-checks it locally** — before exposing anything publicly, it curls the function directly on the runner with the Function URL's own `Host` header, to confirm routing works before troubleshooting would require going through the tunnel.
4. **Starts a Cloudflare Quick Tunnel** — downloads the official `cloudflared` binary and starts an ephemeral tunnel pointed at `http://localhost:4566`, then parses the assigned `https://*.trycloudflare.com` URL out of its logs and prints it to the job's step summary and the console.
5. **Holds it open for 10 minutes** — a 10×60-second loop logs progress once a minute so the tunnel (and the printed URL) stays live and visible in the log.
6. **Tears down** — in an `if: always()` step, stops the `cloudflared` background process and removes the LocalStack container, regardless of whether earlier steps succeeded.

## Why `--http-host-header` is required

LocalStack's gateway listens on a single port (4566) for every emulated AWS service, and it decides which Lambda Function URL to invoke by reading the incoming HTTP `Host` header (e.g. `<url-id>.lambda-url.us-east-1.localhost.localstack.cloud:4566`) — not by path.

A Cloudflare Quick Tunnel is a plain reverse proxy: by default it forwards the public `*.trycloudflare.com` request to `http://localhost:4566` with the `Host` header unchanged, i.e. still `xxxx.trycloudflare.com`. LocalStack doesn't recognize that as any function and the request would fail. Passing `cloudflared` the `--http-host-header "<lambda-function-url-host>"` flag makes it rewrite the `Host` header to the Lambda's own function-url domain on every proxied request, so LocalStack routes public traffic straight to `hello-world` no matter what public domain the browser actually connects to.

## Running it

1. Go to the **Actions** tab → **LocalStack Cloudflare Tunnel Demo** → **Run workflow**.
2. Approve the `localstack` environment deployment if prompted.
3. Once the job reaches the "Publish tunnel URL" step, the public `https://*.trycloudflare.com` URL is printed in the step summary and the console logs — open it in a browser to see the Lambda's response.
4. The tunnel and LocalStack are automatically torn down after the 10-minute hold, whether the run succeeded or failed.
