# Changelog

## 0.0.1

First public release.

- Monitor OpenAI public status, incidents, maintenance, components and Status API integrity.
- Monitor authenticated OpenAI Platform organization and project data using an Admin API key.
- Collect usage, costs, rate limits, access inventory, project cost/usage allocation, prompt-cache metrics, and caller/API-key attribution.
- Provide dynamic project-service discovery and consolidated monitoring policies without hard-coded inventory totals.
- Include Checkmk check manuals for all shipped checks and packaged OpenAI dashboards.
- Include optional OpenTelemetry runtime integration for eligible Checkmk Ultimate deployments, with REST setup helper and documentation.
- Sanitize upstream API errors so API-key fragments are not exposed in monitoring output.
