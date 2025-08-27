from google.cloud import secretmanager
from google.auth.exceptions import DefaultCredentialsError
from google.api_core.exceptions import PermissionDenied, NotFound
import subprocess

# Import the Secret Manager client library.

# GCP project in which to store secrets in Secret Manager.
PROJECT_ID = "billing-sync"


def test_gcloud_access():
    """Test if we have access to Google Cloud Secret Manager before attempting to use it."""
    try:
        # Check if credentials are available
        client = secretmanager.SecretManagerServiceClient()

        # Test basic access by listing secrets (this will fail if no access)
        parent = f"projects/{PROJECT_ID}"
        try:
            # Try to list secrets - this requires minimal permissions
            secrets_list = list(client.list_secrets(request={"parent": parent}))
            print(f"Google Cloud access verified. Found {len(secrets_list)} secrets available.")
            return True
        except (PermissionDenied, NotFound) as e:
            print(f"Google Cloud access denied or project not found: {e}")
            return False
    except DefaultCredentialsError:
        print("Google Cloud credentials not found. Please ensure GOOGLE_APPLICATION_CREDENTIALS is set correctly.")
        return False
    except Exception as e:
        error_message = str(e)
        # Check if this is a reauthentication error
        if "Reauthentication is needed" in error_message and "gcloud auth application-default login" in error_message:
            print("Google Cloud authentication expired. Attempting automatic reauthentication...")
            try:
                print("Opening browser for Google Cloud authentication...")
                print("Please complete the authentication in your browser.")
                print("This may take a few moments...")
                # Run gcloud auth application-default login
                # Use full path to gcloud.cmd for Windows compatibility
                # Remove timeout since this is an interactive command that opens a browser
                gcloud_path = r"C:\Users\AngusMcLauchlan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
                result = subprocess.run(
                    [gcloud_path, "auth", "application-default", "login"],
                    capture_output=True,
                    text=True,
                    check=False
                    # Removed timeout since this opens a browser and requires user interaction
                )

                if result.returncode == 0:
                    print("Reauthentication successful! Retrying Google Cloud access...")
                    # Retry the access test after successful authentication
                    return test_gcloud_access()
                else:
                    print(f"Reauthentication failed: {result.stderr}")
                    print("Please run 'gcloud auth application-default login' manually.")
                    return False
            except FileNotFoundError:
                print("gcloud command not found. Please ensure Google Cloud SDK is installed.")
                return False
            except Exception as auth_error:
                print(f"Error during reauthentication: {auth_error}")
                print("Please run 'gcloud auth application-default login' manually.")
                return False
        else:
            print(f"Failed to access Google Cloud: {e}")
            return False


def create_secret(secret_id):
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the parent project.
    parent = f"projects/{PROJECT_ID}"

    # Build a dict of settings for the secret
    secret = {'replication': {'automatic': {}}}

    # Create the secret
    try:
        response = client.create_secret(
            secret_id=secret_id, parent=parent, secret=secret)
        # Print the new secret name.
        print(f'Created secret: {response.name}')
    except Exception as exception:  # pylint: disable=broad-except
        print(f"Error: {str(exception)}")


def add_secret_version(secret_id, payload):
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the parent secret.
    parent = f"projects/{PROJECT_ID}/secrets/{secret_id}"

    # Convert the string payload into a bytes. This step can be omitted if you
    # pass in bytes instead of a str for the payload argument.
    payload = payload.encode('UTF-8')

    # Add the secret version.
    response = client.add_secret_version(
        parent=parent, payload={'data': payload})

    # Print the new secret version name.
    print(f'Added secret version: {response.name}')


def access_secret_version(the_project_id, secret_id, version_id):
    """
    Access the payload for the given secret version if one exists. The version
    can be a version number as a string (e.g. "5") or an alias (e.g. "latest").
    """
    # pylint: disable=unused-argument
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the secret version.
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"

    # Access the secret version.
    response = client.access_secret_version(request={"name": name})

    return response.payload.data.decode("UTF-8")


def access_secret_json(the_project_id, secret_id, version_id):
    """
    Access the payload for the given secret version if one exists. The version
    can be a version number as a string (e.g. "5") or an alias (e.g. "latest").
    """
    # pylint: disable=unused-argument
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the secret version.
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"

    # Access the secret version.
    response = client.access_secret_version(request={"name": name})

    return response.payload.data.decode("UTF-8")


def delete_secret(the_project_id, secret_id):
    """
    Delete the secret with the given name and all of its versions.
    """
    # pylint: disable=unused-argument
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the secret.
    name = client.secret_path(PROJECT_ID, secret_id)

    # Delete the secret.
    client.delete_secret(request={"name": name})


def list_secrets(the_project_id):
    """
    List all secrets in the given project.
    """
    # pylint: disable=unused-argument
    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the parent project.
    parent = f"projects/{PROJECT_ID}"

    # List all secrets.
    for secret in client.list_secrets(request={"parent": parent}):
        print(f"Found secret: {secret.name}")


print("Secret Manager: started")
