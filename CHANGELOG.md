# Changelog

## 0.1.0 — 2026-10-07

- `Automation`: environment variables (required, default, secret, cast), dry run, masked log, summary
  (`OPENSCALE_SUMMARY`), artifacts (`OPENSCALE_ARTIFACTS`), exit codes 0/1/2/130.
- `OpenScaleClient`: JSON, bearer token, retries with backoff, writes skipped in a test run.
- `validate_manifest` / `load_manifest` and `python -m openscale_sdk validate` for `openscale.yaml` (schema 1).
- `mask_phone`, `mask_email`.
