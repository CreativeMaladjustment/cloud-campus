# Infrastructure as Code (IaC) Scanning

This repository uses GitHub Actions to automatically run linting and security scans on our Infrastructure as Code (IaC) files, including Terraform and CloudFormation templates. This ensures code quality, consistency, and security before changes are deployed.

## Tools Used

The following tools are integrated into the `IaC Scan` workflow (`.github/workflows/iac-scan.yaml`):

### 1. Terraform Format and Lint (`terraform fmt` and `tflint`)
*   **`terraform fmt`**: This built-in Terraform command checks that all Terraform configuration files adhere to standard formatting conventions. It ensures a consistent code style across the project, making it easier to read and review.
*   **`tflint`**: A Terraform linter focused on possible errors, best practices, and checking cloud provider-specific rules. It goes beyond syntax checking to identify issues like invalid instance types, deprecated syntax, or unused declarations.

### 2. CloudFormation Linter (`cfn-lint`)
*   **`cfn-lint`**: An open-source tool provided by AWS to validate AWS CloudFormation YAML/JSON templates against the AWS CloudFormation Resource Specification. It checks for valid resource properties, correct types, and adherence to best practices, catching errors before deployment.

### 3. Checkov Security Scanner
*   **Checkov**: A static code analysis tool for infrastructure as code. It scans cloud infrastructure configurations to find misconfigurations that could lead to security or compliance issues before they are deployed.

## The Value of Checkov

Checkov is a critical component of our CI/CD pipeline because it acts as an automated security gate. Its key benefits include:

*   **Proactive Security**: Checkov identifies security misconfigurations (like open `0.0.0.0/0` security group rules, unencrypted S3 buckets, or overly permissive IAM policies) *before* the infrastructure is provisioned, preventing vulnerabilities from reaching production.
*   **Compliance Verification**: It comes with hundreds of built-in policies that map to common compliance standards (e.g., CIS, HIPAA, PCI-DSS), helping ensure our infrastructure remains compliant from the start.
*   **Multi-IaC Support**: Checkov is versatile and can scan both Terraform (`.tf`) and CloudFormation (`.yaml`/`.json`) files, providing a unified security scanning experience across our different IaC tools.
*   **Developer Feedback**: By running in GitHub Actions, it provides immediate feedback to developers on pull requests, allowing them to fix security issues early in the development lifecycle.

The Checkov step is currently configured to run with the `--soft-fail` flag, meaning it will report issues but will not block the pipeline. This is useful for gaining visibility into current security posture without immediately breaking builds, with the intention of addressing the findings over time.
