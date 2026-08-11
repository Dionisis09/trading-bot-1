# Vendored dashboard runtime

`data-analytics-plugin` is the local OpenAI Data Analytics portable-artifact
runtime version `0.2.8-13ceeea1f599` used by `dashboard-builder`.

It is copied into the project so the exact same canonical dashboard builder
works on Windows and on a remote Linux VPS without a machine-specific Codex
cache path. Treat it as third-party runtime code: do not edit it locally.
