# PowerShell script for testing the Zendesk backup script locally

# Check if Python is activated in a virtual environment
if (-not (Test-Path '.\.venv\Scripts\Activate.ps1')) {
    Write-Host 'Python virtual environment not found. Creating one now...'
    python -m venv .venv
}

# Activate virtual environment
Write-Host 'Activating Python virtual environment...'
.\.venv\Scripts\Activate.ps1

# Install dependencies if not already installed
Write-Host 'Installing dependencies...'
pip install -r requirements.txt

# Check if client_secrets.json exists, if not, prompt user
if (-not (Test-Path './client_secrets.json')) {
    Write-Host '⚠️ client_secrets.json file not found!' -ForegroundColor Yellow
    Write-Host 'Please create a Google Cloud project and download OAuth client credentials:' -ForegroundColor Yellow
    Write-Host '1. Go to https://console.cloud.google.com/apis/credentials' -ForegroundColor Cyan
    Write-Host '2. Create OAuth client ID for Desktop application' -ForegroundColor Cyan
    Write-Host '3. Download the JSON file and save as client_secrets.json in this directory' -ForegroundColor Cyan
    
    $continue = Read-Host "Press Enter to continue once you've created the client_secrets.json file, or type 'skip' to try using existing credentials"
    if ($continue -ne 'skip' -and -not (Test-Path './client_secrets.json')) {
        Write-Host 'client_secrets.json file still not found. Exiting...' -ForegroundColor Red
        exit 1
    }
}

# Set environment variables for testing
Write-Host 'Setting environment variables...'
$env:DRIVE_FOLDER_ID = '1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2'
$env:CLIENT_SECRETS_FILE = './client_secrets.json'
$env:TOKEN_PICKLE_FILE = './token.pickle'
$env:USE_FIRESTORE_STORAGE = 'False'  # Set to True if you want to use Firestore

# Run the backup script
Write-Host 'Running backup script...'
Write-Host 'Note: A browser window may open for Google OAuth authentication' -ForegroundColor Cyan
python backup_zendesk_support_tickets.py

# Deactivate virtual environment
deactivate
Write-Host 'Test completed.'