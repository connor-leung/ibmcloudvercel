---
title: Privacy Policy
nav_order: 11
---

# Privacy Policy

**Last updated: March 2026**

## 1. Overview

This Privacy Policy describes how the IBM Cloud Code Engine Vercel Integration ("the Integration") handles information when you install and use it.

## 2. Information Collected

The Integration processes the following data sent by Vercel during deployment events:

- Deployment ID and status
- Git repository owner and name
- Git commit SHA and branch reference
- Vercel project ID and project name
- Vercel access tokens (stored temporarily to report deployment status via the Checks API)

No personally identifiable information beyond what Vercel includes in webhook payloads is collected.

## 3. How Information Is Used

Data is used solely to:
- Authenticate with IBM Cloud and trigger Code Engine deployments
- Report deployment status back to Vercel via the Checks API
- Log errors for debugging purposes

## 4. Data Retention

Access tokens and installation metadata are stored in a local file on the integration backend server. Deployment event data is not persisted beyond the duration of the deployment job.

## 5. Third Parties

The Integration communicates with:
- **Vercel API** — to report deployment check status
- **IBM Cloud APIs** — to create and update Code Engine applications

No data is shared with any other third parties.

## 6. Security

Webhook payloads are verified using HMAC-SHA1 signatures to ensure they originate from Vercel. Communication with all external APIs occurs over HTTPS.

## 7. Changes

This policy may be updated from time to time. Continued use of the Integration constitutes acceptance of any changes.

## 8. Contact

For privacy questions, contact: connorleung.dev@gmail.com