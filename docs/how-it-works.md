---
title: How it works
nav_order: 4
---

# How it works

## Overview

ibmcloudvercel is a small HTTP service that bridges Vercel's deployment webhook system and IBM Cloud Code Engine. When you push code, the chain looks like this:

```
Git push
  → Vercel detects new commit
  → Vercel fires deployment.created webhook
  → ibmcloudvercel receives and verifies the event
  → ibmcloudvercel queues an async deploy job
  → IBM Cloud Code Engine builds and deploys your app
```

---

## The integration server

The server (`src/integration/server.py`) exposes three lifecycle endpoints used by Vercel integrations, plus the webhook receiver:

| Endpoint | Method | Description |
|---|---|---|
| `/integration/health` | GET | Health check — returns `{"status": "ok"}` |
| `/integration/webhook` | POST | Receives Vercel webhook events |
| `/integration/install` | POST | Called when the integration is installed |
| `/integration/update` | POST | Called when the integration is updated |
| `/integration/uninstall` | POST | Called when the integration is removed |

---

## Webhook verification

Every incoming webhook is verified using HMAC-SHA1 against the `x-vercel-signature` header. Requests with missing or invalid signatures are rejected with a `401`.

The secret is read from `VERCEL_WEBHOOK_SECRET` (or `INTEGRATION_WEBHOOK_SECRET`) in the environment.

---

## Async job processing

Webhook events are not processed inline — they are pushed onto an in-process queue and handled by a background worker thread. This means the webhook endpoint returns immediately (HTTP 202) while the deploy runs asynchronously.

Only `deployment.created` events trigger a deploy. All other event types are acknowledged and ignored.

---

## The deploy command

When a `deployment.created` event is dequeued, the worker runs the deploy command configured via `INTEGRATION_DEPLOY_COMMAND` (defaults to `python3 deploy_ibm.py --build`).

The following environment variables are injected into the deploy command's environment:

| Variable | Source |
|---|---|
| `VERCEL_DEPLOYMENT_ID` | Webhook payload |
| `VERCEL_PROJECT_ID` | Webhook payload |
| `VERCEL_GIT_COMMIT_SHA` | Webhook payload metadata |
| `VERCEL_GIT_COMMIT_REF` | Webhook payload metadata |
| `VERCEL_GIT_REPO_OWNER` | Webhook payload metadata |
| `VERCEL_GIT_REPO_SLUG` | Webhook payload metadata |
| `VERCEL_INSTALLATION_TOKEN` | Stored installation record |

---

## App naming

Code Engine application names must be valid RFC 1123 DNS labels (lowercase, alphanumeric and hyphens only, max 63 characters). ibmcloudvercel automatically sanitizes the Git branch name into a valid label, so branches like `feature/my-thing` become `myproject-feature-my-thing`.
