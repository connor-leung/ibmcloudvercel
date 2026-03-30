# [IBMCloudVercel](https://vercel.com/marketplace/ibmcloudvercel)

A Python-based connector that enables seamless deployment of Vercel projects to **IBM Cloud Code Engine**.

## Overview

IBMCloudVercel integrates into your Vercel build pipeline and automatically deploys your application to IBM Cloud Code Engine, providing a sophisticated multi-cloud deployment solution.

## Features

- **Automated Deployment**: Deploys directly from Vercel CI to IBM Cloud Code Engine
- **Preview Deployments**: Creates separate Code Engine apps for each git branch/PR
- **OIDC Authentication**: Secure keyless authentication via Vercel OIDC tokens (no static secrets!)
- **Vercel Integration**: Reports deployment status via Vercel Checks API
- **Configurable Scaling**: Define min/max instances, CPU, memory via YAML config

### Project Structure

```text
ibmcloudvercel/
├── src/
│   └── ibm_cloud_vercel/
│       ├── core/
│       │   └── config.py          # Configuration parser
│       ├── sdk/
│       │   └── auth.py            # IBM Cloud authentication
│       └── integration/
│           └── service.py         # Integration backend service
├── deploy_ibm.py                  # Main entry point
├── ibmcloudvercel.example.yml     # Configuration template
├── pyproject.toml                 # Python project metadata
└── requirements.txt               # Dependencies
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Your Deployment

Copy the example configuration and fill in your IBM Cloud details:

```bash
cp ibmcloudvercel.example.yml ibmcloudvercel.yml
```

Edit [ibmcloudvercel.yml](ibmcloudvercel.yml) with your:

- IBM Cloud region
- Code Engine project ID
- (Recommended) IBM Trusted Profile ID for OIDC authentication

### 3. Authentication Setup

**Option A: OIDC Authentication (Recommended - Most Secure)**

Use Vercel's OIDC tokens with IBM Trusted Profiles:

```yaml
# In ibmcloudvercel.yml
ibm_cloud:
  trusted_profile_id: "Profile-xxxx-xxxx-xxxx"
```

**Option B: API Key Authentication (Fallback)**

Set environment variables in Vercel project settings:

```bash
export IBM_CLOUD_API_KEY="your-ibm-cloud-api-key"
```

### 4. Run Deployment

```bash
python deploy_ibm.py
```

For local validation without mutating IBM Cloud resources:

```bash
IBM_CLOUD_VERCEL_DRY_RUN=true python deploy_ibm.py
```

## Examples

Ready-to-copy integration files are available in [`starters/nextjs/`](starters/nextjs/):

- `Dockerfile` — multi-stage Next.js build for Code Engine (port 8080, non-root user)
- `next.config.ts` — required `output: 'standalone'` setting
- `ibmcloudvercel.yml` — configuration template

## Integration Backend Mode

Use integration mode when running as a Vercel integration backend service instead of a local CLI build.

### Start Integration Service

```bash
python integration_service.py
```

Environment variables:

- `INTEGRATION_HOST` (default: `127.0.0.1`)
- `INTEGRATION_PORT` (default: `8787`)
- `INTEGRATION_STORE_PATH` (default: `.ibmcloudvercel/installations.json`)
- `VERCEL_WEBHOOK_SECRET` (required for webhook signature verification)
- `INTEGRATION_DEPLOY_COMMAND` (default: `python deploy_ibm.py`)
- `INTEGRATION_UNINSTALL_CLEANUP_COMMAND` (optional best-effort cleanup command on uninstall)

Endpoints:

- `GET /integration/health`
- `POST /integration/install`
- `POST /integration/update`
- `POST /integration/uninstall`
- `POST /integration/webhook`

Install/update request example:

```json
{
  "installation_id": "ins_123",
  "access_token": "vercel_installation_token",
  "team": { "id": "team_123", "slug": "acme" },
  "project": { "id": "prj_123", "name": "my-app" }
}
```

Uninstall request example:

```json
{
  "installation_id": "ins_123"
}
```

Webhook request notes:

- `x-vercel-signature` is required and validated using HMAC-SHA1 over the raw request body.
- Supported events: `deployment.created`, `deployment.ready`
- Webhooks return immediately with `202` and are processed asynchronously by an in-process worker queue.
- In integration mode, stored installation access tokens are forwarded to checks reporting.

### Integration Setup Flow (IBM + Vercel)

1. Provision IBM Cloud resources:
   - Code Engine project (`ibm_cloud.project_id`)
2. Configure authentication:
   - Preferred: set `ibm_cloud.trusted_profile_id` and run in Vercel with `VERCEL_OIDC_TOKEN`.
   - Fallback: set `IBM_CLOUD_API_KEY`.
3. Configure deploy image:
   - Set `IBM_CODE_ENGINE_IMAGE_REFERENCE` (or `IBM_CODE_ENGINE_IMAGE`).
4. Deploy this integration backend publicly (HTTPS required).
5. Set integration service environment variables:
   - Required: `VERCEL_WEBHOOK_SECRET`, `IBM_CODE_ENGINE_IMAGE_REFERENCE`
   - Optional: `INTEGRATION_DEPLOY_COMMAND`, `INTEGRATION_UNINSTALL_CLEANUP_COMMAND`
6. Use the manifest template:
   - Copy `integration-manifest.example.json` to your integration provider config.
   - Set lifecycle URLs to your public backend base URL + endpoints.
7. Install integration in Vercel and verify:
   - `POST /integration/install` stores installation token/scope.
   - Signed webhook events enqueue jobs and run deployment asynchronously.

### Integration Manifest and Required Scopes

- Manifest template: `integration-manifest.example.json`
- Required lifecycle endpoints:
  - `/integration/install`
  - `/integration/update`
  - `/integration/uninstall`
  - `/integration/webhook`
- Required webhook events:
  - `deployment.created`
  - `deployment.ready`
- Required access capabilities:
  - Read deployment/project context
  - Write deployment checks status

Validate exact scope keys against current Vercel manifest schema before publishing.

### Required Environment Variables

Core deployment:

- `IBM_CODE_ENGINE_IMAGE_REFERENCE` (required unless `IBM_CODE_ENGINE_IMAGE` is set)
- `IBM_CODE_ENGINE_IMAGE` (optional fallback image variable)
- `IBM_CLOUD_API_KEY` (required when OIDC is unavailable)
- `VERCEL_OIDC_TOKEN` (required for OIDC flow)

Integration backend:

- `VERCEL_WEBHOOK_SECRET` (required for webhook signature verification)
- `INTEGRATION_HOST` (optional; defaults to `127.0.0.1`)
- `INTEGRATION_PORT` (optional; defaults to `8787`)
- `INTEGRATION_STORE_PATH` (optional; defaults to `.ibmcloudvercel/installations.json`)
- `INTEGRATION_DEPLOY_COMMAND` (optional; defaults to `python deploy_ibm.py`)
- `INTEGRATION_UNINSTALL_CLEANUP_COMMAND` (optional; command executed after uninstall record deletion)

### Operational Runbook

Startup:

1. Start service with `python integration_service.py`.
2. Verify `GET /integration/health` returns `{"status":"ok"}`.
3. Confirm logs show store path and webhook endpoint.

Install/update verification:

1. Send install payload to `POST /integration/install`.
2. Confirm response contains persisted installation metadata.
3. Repeat with `POST /integration/update` when token rotates.

Webhook processing:

1. Ensure every request to `POST /integration/webhook` includes `x-vercel-signature`.
2. Expect `202` for queued supported events.
3. Check logs for async job execution and deploy command exit code.

Failure handling:

1. `401` from webhook endpoint: check `VERCEL_WEBHOOK_SECRET` and signature generation.
2. Checks not updating: confirm installation token exists in store and `VERCEL_TEAM_ID` scope is set by payload.
3. Code Engine failures: inspect deploy logs for explicit IAM/Code Engine error details.

Dry-run local validation:

1. Run `IBM_CLOUD_VERCEL_DRY_RUN=true python deploy_ibm.py`.
2. Confirm payload generation and plan output without IBM mutations.

### Uninstall and Cleanup Behavior

Current behavior on `POST /integration/uninstall`:

1. Installation record is deleted from `INTEGRATION_STORE_PATH`.
2. Optional cleanup command (`INTEGRATION_UNINSTALL_CLEANUP_COMMAND`) is executed best-effort.
3. API response returns both uninstall status and cleanup status.

Recommended cleanup command responsibilities:

- Remove/disable integration-specific Code Engine app(s) if applicable.
- Revoke or rotate any integration-managed credentials/tokens.

Cleanup command environment variables:

- `VERCEL_INTEGRATION_INSTALLATION_ID`
- `VERCEL_TEAM_ID`
- `VERCEL_PROJECT_ID`
- `VERCEL_PROJECT_NAME`

## Configuration Reference

See [ibmcloudvercel.example.yml](ibmcloudvercel.example.yml) for a complete configuration template with comments.

### Required Settings

- `ibm_cloud.region`: IBM Cloud region (e.g., `us-south`)
- `ibm_cloud.project_id`: Code Engine project ID

### Optional Settings

- `scaling.*`: Configure CPU, memory, min/max instances
- `source_dir`: Source directory to deploy (default: `.`)

## Author

Connor Leung
