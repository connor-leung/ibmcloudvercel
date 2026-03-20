---
title: Authentication
nav_order: 3
---

# Authentication

ibmcloudvercel supports two authentication methods for accessing IBM Cloud. OIDC is strongly recommended.

---

## OIDC via IBM Trusted Profile (Recommended)

This method uses Vercel's built-in OIDC tokens exchanged for short-lived IBM Cloud credentials via an IBM Trusted Profile. No static secrets are stored — tokens are issued per-deployment and expire automatically.

### How to set it up

1. **Create a Trusted Profile** in IBM Cloud IAM:
   - Go to **Manage → IAM → Trusted Profiles**
   - Create a new profile and add a trust relationship for Vercel's OIDC issuer
   - Grant the profile the IAM permissions needed for Code Engine and COS

2. **Note the profile ID** — it looks like `Profile-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

3. **Set the environment variable** in Vercel:
   ```
   IBM_TRUSTED_PROFILE_ID=Profile-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

4. **Add to your config file:**
   ```yaml
   ibm_cloud:
     trusted_profile_id: "${IBM_TRUSTED_PROFILE_ID}"
   ```

---

## API Key (Fallback)

If `trusted_profile_id` is not configured, ibmcloudvercel falls back to using a static IBM Cloud API key.

### How to set it up

1. **Generate an API key** in IBM Cloud IAM:
   - Go to **Manage → IAM → API Keys**
   - Create a key with permissions for Code Engine and COS

2. **Set the environment variable** in Vercel:
   ```
   IBM_CLOUD_API_KEY=your-api-key-here
   ```

No changes to `ibmcloudvercel.yml` are needed — the API key is read directly from the environment.

{: .warning }
> API keys are long-lived static secrets. If exposed, they must be manually rotated. Prefer OIDC where possible.

---

## Required IAM permissions

Whichever method you use, the identity needs at minimum:

| Service | Permission |
|---|---|
| IBM Cloud Code Engine | Writer (to create/update applications and builds) |
| Cloud Object Storage | Writer (to upload source tarballs to the staging bucket) |
