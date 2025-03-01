# Zendesk Backup Service Deployment Guide

This guide explains how to deploy the Zendesk Backup Service to Google Cloud Run with scheduled execution.

## Prerequisites

- Google Cloud Project with billing enabled
- Google Cloud SDK (gcloud) installed
- Docker installed (for local testing)
- Permissions to:
  - Deploy to Cloud Run
  - Create Cloud Scheduler jobs
  - Access Secret Manager
  - Create/access service accounts

## Setup Steps

### 1. Create a Google Drive Folder

1. Go to Google Drive and create a folder to store Zendesk backup files
2. Note the folder ID (found in the URL when you open the folder: `https://drive.google.com/drive/folders/YOUR_FOLDER_ID`)
   - For this project, we're using the folder ID: `1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2`

### 2. Configure Service Account Permissions

1. Create a service account for the Cloud Run service:
   ```bash
   gcloud iam service-accounts create zendesk-backup \
     --display-name="Zendesk Backup Service Account"
   ```

2. Grant necessary permissions:
   ```bash
   # Grant Secret Manager access
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:zendesk-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   
   # Grant Google Drive access (for service account to interact with Drive API)
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:zendesk-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/drive.appdata"
   ```

3. Share the Google Drive folder with the service account email (zendesk-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com) with Editor permissions

### 3. Build and Deploy to Cloud Run

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/zendesk-backup.git
   cd zendesk-backup
   ```

2. Deploy using Cloud Build:
   ```bash
   gcloud builds submit --config=cloudbuild.yaml \
     --substitutions=_DRIVE_FOLDER_ID="1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2"
   ```

### 4. Set Up Cloud Scheduler

1. Create a scheduler job to run the service:
   ```bash
   gcloud scheduler jobs create http zendesk-backup-job \
     --schedule="0 0 * * *" \
     --uri="https://zendesk-backup-YOUR_REGION-run.app" \
     --http-method=POST \
     --oidc-service-account-email="zendesk-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --oidc-token-audience="https://zendesk-backup-YOUR_REGION-run.app"
   ```
   This will run the backup daily at midnight. Adjust the schedule as needed.

## Troubleshooting

### Check Cloud Run Logs

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=zendesk-backup" --limit=50
```

### Test Locally

To test locally with your Google account permissions:

```bash
# Login with ADC - this will open a browser window for authentication
gcloud auth application-default login

# The Drive folder ID is already set in the script as a default value:
# DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID', '1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2')

# Alternatively, you can override it with an environment variable if needed:
# $env:DRIVE_FOLDER_ID="1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2"  # PowerShell syntax

# Activate your Python virtual environment (if you have one)
# .\.venv\Scripts\Activate  

# Run the script
python backup_zendesk_support_tickets.py
```

## Maintenance

### Update the Service

To update the deployed service:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_DRIVE_FOLDER_ID="1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2"
```