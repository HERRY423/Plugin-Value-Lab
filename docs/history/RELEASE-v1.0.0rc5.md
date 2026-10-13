# Plugin Value Lab v1.0.0rc5

Release candidate for the latest plugin evaluation, decision, and distribution changes.
The Git tag is `v1.0.0rc5`; plugin manifests use `1.0.0-rc.5` and Python packages use `1.0.0rc5`.

## Changes

- Add the scientific balance icon to the plugin listing and composer, and include it in marketplace and portable packages.
- Respect the frozen power plan when judging independent task-family coverage. Repeated runs cannot bypass the family requirement; underpowered positive evidence remains a trial-only signal.
- Add bounded action recommendations and 3–32 candidate comparisons with explicit researcher losses, scope, expiry, alternatives, and next evidence. Shrinkage displays cannot bypass independent confirmation gates.
- Add a literature task-family intake and custody-signature workflow, with 30 synthetic candidate placeholders. These are not expert-validated real task families.
- Add request-budget reservations to the parent model gateway, retaining unresolved reservations and rejecting requests beyond the allowed budget before dispatch.
- Render structured Markdown values as readable tables and keep HTML escaping at the HTML layer.
- Consolidate current guidance into the README and retain previous guides and evidence under the history index. Repair installation links in generated marketplace packages.
- Separate fast and full test tiers; release validation rejects skipped tests.

## Install

In **Add plugin marketplace**, use source `HERRY423/Plugin-Value-Lab`, Git reference `v1.0.0rc5`, and leave sparse paths empty. Use `main` instead to follow subsequent repository changes.

For a local installation, download `plugin-value-lab-marketplace-1.0.0-rc.5.zip`, extract the complete archive, and select its marketplace root folder. The portable Agent Plugins archive and Python wheel are separate installation options. Verify downloads with `SHA256SUMS.txt`.

## Evidence and limits

Validation outcomes and package hashes are recorded in the attached `release-evidence.json`. This is a prerelease, not general-availability or native-host certification.

The evidence ladder remains a design proposal. Expert review, independent holdout custody, real plugin benefit, and clinical/scientific validity are not established by the bundled synthetic cases or engineering tests. The gateway reservation mechanism does not establish a provider-side spending limit; the currently authorized $0.10 request ceiling still blocks the configured model's conservative cost envelope.
