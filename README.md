# IBMCloudVercel

A Python-based connector that enables seamless deployment of Vercel projects to **IBM Cloud Code Engine**.

## Overview

IBMCloudVercel integrates into your Vercel build pipeline and automatically deploys your application to IBM Cloud Code Engine, providing a sophisticated multi-cloud deployment solution.

## Features

- **Automated Deployment**: Deploys directly from Vercel CI to IBM Cloud Code Engine
- **Preview Deployments**: Creates separate Code Engine apps for each git branch/PR
- **Source Code Staging**: Uses IBM Cloud Object Storage for secure source transfer
- **Vercel Integration**: Reports deployment status via Vercel Checks API
- **Configurable Scaling**: Define min/max instances, CPU, memory via YAML config

## Phase 1 Complete ✅

The following components have been implemented:

- ✅ Python project structure (src-layout)
- ✅ Configuration parsing ([ibmcloudvercel.yml](ibmcloudvercel.yml))
- ✅ Source code archiving and COS upload
- ✅ Main deployment orchestrator ([deploy_ibm.py](deploy_ibm.py))

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

## Next Steps (Phase 2)

- [ ] Implement Code Engine SDK wrapper
- [ ] Add application create/update logic
- [ ] Implement deployment status polling
- [ ] Extract and return public URL

## License

MIT

## Author

Connor Leung
