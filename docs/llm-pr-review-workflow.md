# LLM PR Review Workflow

This repository includes a GitHub Actions workflow that automatically reviews Pull Requests using a locally running Large Language Model (LLM).

## How it works

The workflow runs entirely on the GitHub Actions runner, without requiring external API keys or incurring costs for LLM usage.

1. **Setup:** It runs an Ollama Docker service container and pulls the lightweight `qwen2.5-coder:1.5b and deepseek-r1:1.5b` model.
2. **Fetch Data:** It uses the GitHub CLI (`gh`) to fetch the PR title, description, and the complete code diff.
3. **Review:** It dynamically generates a prompt for the LLM to review the PR for clarity, completeness, and documentation accuracy based on the code changes.
4. **Comment:** It posts the generated review as a comment directly on the Pull Request.

## Triggers

The workflow can be triggered in two ways:

1. **Automatically:** It runs automatically whenever a new Pull Request is opened (`pull_request: types: [opened]`).
2. **Manually:** It can be triggered manually via the `workflow_dispatch` event. When doing so, you must provide a `pr_url` to review a specific Pull Request.

## Workflow File

The workflow is defined in `.github/workflows/llm-pr-review.yaml`.
