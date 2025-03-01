FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables (these can be overridden at runtime)
ENV DRIVE_FOLDER_ID="1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2"

# Set the CMD to your handler
CMD ["python", "backup_zendesk_support_tickets.py"]