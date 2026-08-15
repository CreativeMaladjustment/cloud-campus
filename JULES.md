# Jules AI Agent Operating Instructions

## 1. Branch & Pull Request Management
You must explicitly verify the state of branches and Pull Requests before starting new work or modifying existing code.
* **Never reuse merged or closed branches.** If the user requests follow-up changes and the previous PR is merged or closed, you MUST create a completely new branch (e.g., `feature-name-followup`) and open a new PR.
* **Check PR Status:** Before committing, verify the remote state to ensure you are not trying to update a completed PR. 

## 2. Remote Syncing Requirement
Code changes do not sync to the remote automatically. 
* You MUST explicitly push your commits to the remote repository. 
* Always execute `git push -u origin <branch-name>` (or the equivalent API push) and verify the push was successful before marking a plan step or task as complete. Check your `git status` to ensure no modified files were left uncommitted.

## 3. Pull Request Standards
When opening a new Pull Request, you must strictly adhere to the following title and description formats.

### PR Title
Use the Conventional Commits standard: `<type>(<optional-scope>): <description>`
* Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
* Example: `feat(auth): implement JWT token refresh`

### PR Description Template
Copy and use this exact markdown template for the PR body:

## Description
[Clear, detailed explanation of the code changes made and why.]

## Motivation / Context
[Explain the problem this solves or the feature it adds based on the user's prompt.]

## Verification
[Detail the exact steps you took to test and verify these changes worked in your VM environment before opening this PR.]
