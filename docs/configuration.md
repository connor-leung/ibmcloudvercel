---
title: Configuration
nav_order: 2
---

# Configuration

ibmcloudvercel is configured via an `ibmcloudvercel.yml` file in your repo root.
If no config file is found, it falls back to reading all values from environment variables.

All string values support environment variable expansion:

```yaml
region: "${IBM_CLOUD_REGION}"          # required, error if not set
region: "${IBM_CLOUD_REGION:-us-south}" # with default fallback
```

---

## ibm_cloud

Required section. Defines your IBM Cloud credentials and target project.

```yaml
ibm_cloud:
  region: "${IBM_CLOUD_REGION:-us-south}"
  project_id: "${IBM_CODE_ENGINE_PROJECT_ID}"
  cos_bucket: "${IBM_COS_BUCKET_NAME}"

  # OIDC auth (recommended)
  trusted_profile_id: "${IBM_TRUSTED_PROFILE_ID}"

  # Optional: custom COS endpoint (auto-detected from region if omitted)
  # cos_endpoint: "${IBM_COS_ENDPOINT}"

  # Optional: container registry pull secret name
  # registry_secret: "${IBM_REGISTRY_SECRET}"
```

| Key | Required | Description |
|---|---|---|
| `region` | Yes | IBM Cloud region (e.g. `us-south`, `eu-gb`, `jp-tok`) |
| `project_id` | Yes | Code Engine project UUID from IBM Cloud Console |
| `cos_bucket` | Yes | Cloud Object Storage bucket for staging source tarballs |
| `trusted_profile_id` | No | IBM Trusted Profile ID for OIDC auth (recommended) |
| `cos_endpoint` | No | Custom COS endpoint — auto-detected from region if omitted |
| `registry_secret` | No | Pull secret name for private container registries |

---

## scaling

Optional. Controls how Code Engine scales your application. Sensible defaults are applied if omitted.

```yaml
scaling:
  min_scale: 0       # scale to zero when idle
  max_scale: 10      # maximum instances
  cpu: "0.25"        # vCPUs per instance (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
  memory: "0.5G"     # memory per instance (0.5G, 1G, 2G, 4G, 8G, 16G, 32G)
  port: 8080         # port your app listens on
  concurrency: 100   # max concurrent requests per instance
```

Setting `min_scale: 0` means Code Engine will scale your app down to zero when it has no traffic — you only pay for active compute time.

---

## Deployment options

```yaml
source_dir: "."          # directory containing source code (relative to repo root)
cleanup_artifacts: true  # delete staged COS object after deploy
```

---

## Environment variable fallback

If `ibmcloudvercel.yml` is not present, the following environment variables are used directly:

| Variable | Maps to |
|---|---|
| `IBM_CLOUD_REGION` | `ibm_cloud.region` |
| `IBM_CODE_ENGINE_PROJECT_ID` | `ibm_cloud.project_id` |
| `IBM_REGISTRY_SECRET` | `ibm_cloud.registry_secret` |
| `IBM_GIT_SOURCE_SECRET` | `ibm_cloud.git_source_secret` |
| `IBM_CLOUD_TRUSTED_PROFILE_ID` | `ibm_cloud.trusted_profile_id` |
| `IBM_CODE_ENGINE_SOURCE_DIR` | `source_dir` |
