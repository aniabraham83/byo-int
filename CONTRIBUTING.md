# Contributing

Thanks for helping improve BYOINT.

## Ground Rules

- Be respectful and constructive in issues and pull requests.
- Keep changes focused and easy to review.
- Do not include secrets, private keys, or production data in commits.

## Development Setup

1. Copy `.env.example` to `.env` and set safe local credentials.
2. Start services:
   - `docker compose -f docker-compose.yml up -d --build`
3. Run security checks before opening a PR:
   - `powershell -ExecutionPolicy Bypass -File scripts/run-security-scan.ps1`

## Pull Request Checklist

- Explain what changed and why.
- Include test or validation steps.
- Update docs when behavior changes.
- Confirm no sensitive values were committed.

## Commit Style

Use clear, imperative commit messages.

Examples:

- `Add API key rotation endpoint`
- `Fix datapull queue status response`
- `Update docs for bootstrap workflow`
