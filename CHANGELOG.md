# Changelog

## 0.3.2 — November 27, 2026

- Make cook controls opt-in for new and existing installations. Sensors and cook notifications work in read-only mode. Enable controls in the integration options to use Start, Continue and End.
- Retry temporary token-refresh failures, including rate limits and server outages. Prompt for sign-in when the token endpoint explicitly rejects the refresh token.
- Remove the unused Cancel cook button and load the public Firebase client key from a Python constant.

## 0.3.1 — November 15, 2026

- Default setup to normal account sign-in; propagate duplicate-account flow aborts.
- Migrate Bluetooth lookup to the current device-registry API.
- Show the terminal cleanup stage as Cook complete without a false cooking estimate.
- Add explicit read-only recovery for uncertain starts; never replay a hub command or history POST.
- Add Marketplace metadata, documentation, validation workflows and regression tests.

## 0.3.0 — November 15, 2026

- Add server cook-history creation and exact session/account association verification.
- Normalize probe addresses to the lowercase format used by the official app.
- Keep Start and Continue separate; never automatically activate the first step.
- Verify current paused notification before Continue.
- End only the selected cook and verify other sessions remain.
- Persist write intent before starting a cook; block duplicate starts after uncertain outcomes.
- Restore Start/Continue/End availability after successful app/hub validation. Legacy Cancel stays disabled.
- Preserve Wi-Fi/Bluetooth aggregation and persistent step alerts.

## 0.2.2

- Disable experimental cook writes following a hub reset during a live test.
- Correct nested alert parsing and unknown-time sentinels.
