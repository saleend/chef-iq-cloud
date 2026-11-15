# Reporting security issues

Do not put passwords, refresh tokens, signed WebSocket URLs, Home Assistant config-entry exports or raw protocol captures into public issues. Redact account and device identifiers from diagnostics.

If a repository is published, use its private security reporting feature when available. Otherwise report only that you found a security issue and ask the maintainer for a private reporting channel; do not post the exploit or credentials publicly.

The public Firebase project identifier/API key in app_config.json is part of the app client configuration. Account passwords and refresh/session tokens are different and must remain private.
