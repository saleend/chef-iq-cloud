# Marketplace submission preparation

Prepared for GitHub maintainer `saleend`, repository `chef-iq-cloud`. See the GitHub Actions runs for the release checks and the Releases page for the published version. Marketplace catalog submission is a separate step.

## Before catalog submission

1. Review the source and the MIT license. Create the GitHub repository with this folder as its root, a description, issues enabled and relevant topics. Use a public repository when ready for distribution.
2. The registry deprecation, setup defaults, completed-step display and uncertain-write recovery are fixed in0.3.1. Continue expanding HA integration tests and hardware/account coverage. The earlier hub reset cause is still unconfirmed.
3. Run `.github/workflows/validate.yaml` and `hassfest.yaml` on the actual repository and fix every reported issue. Use the actual passing workflow run links as evidence. Do not skip catalog checks.
4. Publish a full GitHub release whose tag matches the integration manifest version. Review README claims and limitations against the release actually published.
5. Users can add the repository directly to Marketplace while catalog review is pending. Generate a My Home Assistant `marketplace_repository` link with the actual owner/repository/category=integration.
6. As owner or major contributor, open a PR to the `integration` list in `hacs/default`, alphabetically adding `saleend/chef-iq-cloud`. The built-in Marketplace still reads that catalog. Complete its template with the release and passing validation links. Do not request reviewers.

## Official references checked November 15, 2026

- [Publish a custom integration](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [Get into the catalog](https://contributors.home-assistant.io/marketplace/guides/catalog/)
- [Repository metadata: hacs.json](https://contributors.home-assistant.io/marketplace/reference/hacs-json/)
- [Validation checks](https://contributors.home-assistant.io/marketplace/reference/validation/)

The metadata file and catalog validator retain HACS names even though the user-facing installation target is the built-in Marketplace. Marketplace listing is separate from inclusion in HA core. This integration uses its own `chef_iq_cloud` domain and does not replace the built-in `chef_iq` integration.
