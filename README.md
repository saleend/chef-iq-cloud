# CHEF iQ Cloud + Bluetooth

An unofficial Home Assistant custom integration for CHEF iQ thermometer hubs. Adds Wi-Fi readings, fresh-source Wi-Fi/Bluetooth temperature selection, cook monitoring, and manual cook controls synchronized with the CHEF iQ app and hub.

Maintainer: [@saleend](https://github.com/saleend). Version 0.3.1 is an early release. Cook control was tested on one CQ60-3C-HUB, three probes, and Home Assistant 2026.11.1. It is not yet listed in Home Assistant Marketplace.

## Features

- Wi-Fi food and ambient temperatures from the hub's cloud connection.
- Combined temperatures select the freshest valid Wi-Fi or official CHEF iQ Bluetooth reading. They do not average readings.
- Active cook names, targets, step definitions and timers, including app-created cooks.
- Manual cook name, target, optional flip/wrap thresholds, and rest timer.
- Start creates the hub session and the cloud history association the app needs.
- Continue explicitly advances the current paused step. A new cook normally waits for heat detection; Start does not automatically send Continue.
- End affects the selected probe's session and verifies other sessions remain.
- Hub step events produce persistent HA notifications and `chef_iq_cook_notification` events.

Existing official Bluetooth integration entities remain available. Recipe browsing, the CHEF iQ preset calculator, editing an existing cook, mobile push notification setup, and the old Cancel action are not implemented.

## Install

[![Open in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=saleend&repository=chef-iq-cloud&category=integration)

Open the link above to add this repository to the built-in Marketplace as a custom integration repository, then install it. It can be installed directly while catalog listing is pending. This uses the current `hacs.json` metadata format.

For manual installation, copy `custom_components/chef_iq_cloud` into your HA configuration's `custom_components` folder, then restart HA. Add **CHEF iQ Cloud + Bluetooth** under Settings → Devices & services. Enter your CHEF iQ email and password; saved-session import is off by default. The saved-session option is a development migration feature; ordinary installations should sign in normally.

The optional Bluetooth source requires the official CHEF iQ integration and suitable Bluetooth coverage. The cloud source requires the hub to be online and linked to the account.

## Controls

Each discovered probe has cook name/target/flip/wrap/rest entities and Start, Continue and End buttons. Cook temperature settings are explicitly **°F** and rest is in minutes; zero disables an optional setting. Editing these entities configures the next cook and does not edit an active cook.

Use HA's entity picker to add the controls to your dashboard. `examples/probe-controls.yaml` is an optional card example. This integration does not install a dashboard or modify an existing one.

New cooks wait for heat detection as in the official app. Use Continue if you want to start the current paused step explicitly. Continue also acknowledges a paused transition, such as starting rest after remove-from-heat. End is available for an active session.

If a start times out or only partly succeeds, inspect the official app before retrying. The persistent journal blocks another start after an uncertain write; restarting HA does not replay it. After inspecting the app and allowing pending commands to settle, press **Check previous cook start**. This reads fresh hub state and history links without replaying a write. A linked active cook is marked verified; an absent session is marked resolved. An active cook with no history link stays blocked: end that session explicitly, then check again.

## Verified behavior and limitations

The end-to-end HA dashboard test on November 15, 2026 created a spare-probe cook visible in the official app with the correct probe, live temperature, name and target. HA Continue advanced the app, remove-from-heat and a one-minute rest-complete alert reached HA, the app showed Cook Complete, and HA End produced the app's “ended from another device” message. A separate pork cook remained active throughout. Offline tests cover cook models, transaction failure boundaries, recovery and manager actions.

An earlier experimental version preceded a hub reset that cleared existing sessions. The root cause remains unconfirmed. This version adds the missing app history flow, normalizes probe address casing, removes automatic immediate first-step activation, checks the current loaded step, and journals starts before writing. The successful bounded test does not establish long-term stability across all firmware, models or accounts. Begin additional testing with spare probes.

Other limits: region behavior beyond the tested US endpoints is unverified; simultaneous account sessions worked during this test but long-term compatibility is unconfirmed; audible hub announcements were not independently verified. The completed-cook cleanup stage is shown as Cook complete, and Bluetooth discovery uses the current multi-device registry API.

## Credentials and privacy

The password is used for sign-in and is never stored. HA stores the account refresh token in its config entry. Treat HA configuration backups as sensitive. Cloud data travels to CHEF iQ, Firebase and AWS endpoints used by the installed app. Logs omit raw signed URLs, tokens and payloads. The bundled Firebase API key identifies the public app project; it is not an account session token.

This repository contains no account tokens, device identifiers, private captures, downloaded APKs or app disassembly. For bug reports, redact tokens, email addresses, hub/probe addresses and raw protocol captures. See `SECURITY.md`.

## Development

Run the three scripts in `tests/` from the repository root with Python and `aiohttp` installed. They use synthetic data and mocked HA callbacks and make no network requests. They are not a complete HA integration test suite. GitHub Actions also includes hassfest and Marketplace catalog validation; those checks must pass on the actual repository before submission.

See `SUBMISSION.md` for release and catalog steps, and `CHANGELOG.md` for changes.
