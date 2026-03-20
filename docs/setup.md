---
title: Setup
nav_order: 1
---

# Setup

## Prerequisites

- An [IBM Cloud](https://cloud.ibm.com) account with:
  - A **Code Engine** project
  - A **Cloud Object Storage** bucket (used to stage source code during builds)
- A [Vercel](https://vercel.com) account
- Python 3.9+

---

## 1. Clone the repo

```bash
git clone https://github.com/connorleung/ibmcloudvercel
cd ibmcloudvercel
pip3 install -r requirements.txt
```

---

## 2. Create your config file

```bash
cp ibmcloudvercel.example.yml ibmcloudvercel.yml
```

Edit `ibmcloudvercel.yml` with your IBM Cloud details. See the [Configuration](./configuration) page for all options.

---

## 3. Set environment variables in Vercel

Go to your Vercel project → **Settings** → **Environment Variables** and add:

| Variable | Required | Description |
|---|---|---|
| `IBM_CODE_ENGINE_PROJECT_ID` | Yes | Your Code Engine project UUID |
| `IBM_COS_BUCKET_NAME` | Yes | COS bucket for staging source code |
| `IBM_CLOUD_REGION` | Yes | IBM Cloud region (e.g. `us-south`) |
| `VERCEL_WEBHOOK_SECRET` | Yes | Secret from your Vercel integration settings |
| `IBM_TRUSTED_PROFILE_ID` | Recommended | For OIDC auth — see [Authentication](./auth) |
| `IBM_CLOUD_API_KEY` | Fallback | Used if `IBM_TRUSTED_PROFILE_ID` is not set |

---

## 4. Register the webhook in Vercel

In your Vercel integration or project settings, set the webhook URL to:

```
https://<your-deployment-url>/integration/webhook
```

The integration server listens for `deployment.created` events. When received, it triggers a Code Engine build with the source code from the corresponding Git commit.

---

## 5. Push and verify

Push any change to your repo. You should see:
- A `deployment.created` webhook event fired by Vercel
- A new Code Engine build triggered
- The integration server logs confirming the job was queued and processed

To check the server is running:

```bash
curl https://<your-deployment-url>/integration/health
# {"status": "ok"}
```
