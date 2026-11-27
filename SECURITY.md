# Reporting security issues

Do not put passwords, refresh tokens, signed WebSocket URLs, Home Assistant config-entry exports or raw protocol captures into public issues. Redact account and device identifiers from diagnostics.

If a repository is published, use its private security reporting feature when available. Otherwise report only that you found a security issue and ask the maintainer for a private reporting channel; do not post the exploit or credentials publicly.

The public Firebase project identifier/API key in `custom_components/chef_iq_cloud/const.py` is part of the app client configuration. Account passwords and refresh/session tokens are different and must remain private.

## Expected Firebase client-key alert

GitHub may identify `custom_components/chef_iq_cloud/const.py` as containing a Google API Key. This value is the Firebase client API key distributed with the official CHEF iQ Android app, used by this integration only for Firebase Authentication and session refresh. It is shared app configuration, not a user's email, password, refresh token, or private Google service-account key.

[Firebase's documentation](https://firebase.google.com/docs/projects/api-keys) describes Firebase client keys as public identifiers and explains that backend authorization is enforced separately. Appropriate API restrictions remain the provider's responsibility; this integration cannot audit or change CHEF iQ's Google Cloud project settings and makes no claim about access to unrelated Google APIs.

Review any alert against the actual value and context. An expected client-key finding can be resolved individually as a false positive for secret disclosure. Keep secret scanning enabled, and treat account tokens, private keys, and unexpected credentials as real incidents.
