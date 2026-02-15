# IBMCloudVercel

A Python-based connector that enables seamless deployment of Vercel projects to **IBM Cloud Code Engine**.

## Overview

IBMCloudVercel integrates into your Vercel build pipeline and automatically deploys your application to IBM Cloud Code Engine, providing a sophisticated multi-cloud deployment solution.

## Features

- **Automated Deployment**: Deploys directly from Vercel CI to IBM Cloud Code Engine
- **Preview Deployments**: Creates separate Code Engine apps for each git branch/PR
- **Source Code Staging**: Uses IBM Cloud Object Storage for secure source transfer
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
│       └── sdk/
│           ├── auth.py            # IBM Cloud authentication
│           └── cos.py             # COS upload wrapper
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
- Cloud Object Storage bucket name
- (Recommended) IBM Trusted Profile ID for OIDC authentication

### 3. Authentication Setup

**Option A: OIDC Authentication (Recommended - Most Secure)**

Use Vercel's OIDC tokens with IBM Trusted Profiles:

```yaml
# In ibmcloudvercel.yml
ibm_cloud:
  trusted_profile_id: "Profile-xxxx-xxxx-xxxx"
```

See [OIDC_SETUP.md](OIDC_SETUP.md) for detailed setup instructions.

**Option B: API Key Authentication (Fallback)**

Set environment variables in Vercel project settings:

```bash
export IBM_CLOUD_API_KEY="your-ibm-cloud-api-key"
export IBM_COS_SERVICE_INSTANCE_ID="your-cos-service-crn"
```

### 4. Run Deployment

```bash
python deploy_ibm.py
```

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

Endpoints:

- `GET /integration/health`
- `POST /integration/install`
- `POST /integration/update`
- `POST /integration/uninstall`

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

## Configuration Reference

See [ibmcloudvercel.example.yml](ibmcloudvercel.example.yml) for a complete configuration template with comments.

### Required Settings

- `ibm_cloud.region`: IBM Cloud region (e.g., `us-south`)
- `ibm_cloud.project_id`: Code Engine project ID
- `ibm_cloud.cos_bucket`: Cloud Object Storage bucket name

### Optional Settings

- `scaling.*`: Configure CPU, memory, min/max instances
- `source_dir`: Source directory to deploy (default: `.`)
- `cleanup_artifacts`: Delete COS artifacts after deployment (default: `true`)

## Author

Connor Leung
