# Security Policy

## Supported Versions

Security fixes are prioritized for the latest `main` branch state.

## Reporting a Vulnerability

Please do not open public GitHub issues for suspected vulnerabilities.

1. Use GitHub private vulnerability reporting: open the repository's **Security** tab and
   choose **Report a vulnerability**.
2. Include reproduction steps, impact, and affected components.
3. If possible, include a suggested remediation.

## Disclosure Process

- We will acknowledge reports as soon as practical.
- We will triage severity and affected versions.
- We will work on a fix and coordinate disclosure timing with the reporter.

## Custom Snippet Sandbox and Its Limits

Custom datapull templates and custom data enrichments run user-supplied Python code. The app sends
each snippet to the separate `snippet_runner` container, which runs it in a short-lived process.
That container holds no app secrets or app code, has a read-only filesystem, runs as an
unprivileged user with all capabilities dropped, and has no network route to MongoDB or Redis.
Each snippet process starts with an empty environment and has time, CPU, memory, open-file and
file-size limits. If the runner is unavailable, snippets fail rather than run inside the app.

The import and builtin allowlists reduce accidental misuse but are **not a security boundary**. A
snippet that escapes them can still make outbound network requests (including to hosts on the local
network and to the app's API), use the runner's `/tmp`, and interfere with other snippets running at
the same time. It shares the host's kernel.

- Custom snippets are disabled by default. They run only when an admin enables the
  `allow_custom_snippet` setting in the `core` configuration module.
- Only enable them when every user who can create or edit templates and enrichments is trusted.
- Reports showing that a snippet can escape the allowlists, or do the things described above, are
  expected behavior and are not treated as vulnerabilities.
- In scope: snippets running while `allow_custom_snippet` is off, a non-admin changing that setting,
  a snippet reading app secrets (for example `DATAPULL_SECRET_MASTER_KEY` or `SNIPPET_RUNNER_TOKEN`),
  reaching MongoDB or Redis, writing outside `/tmp` in the runner, running inside the app containers,
  or bypassing the time and resource limits.

## Secrets and Sensitive Data

- Never commit `.env` files or real credentials.
- Rotate any exposed secrets immediately.
- Prefer environment-backed secrets over hardcoded values.
