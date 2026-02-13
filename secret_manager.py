from google.cloud import secretmanager
from google.auth.exceptions import DefaultCredentialsError
from google.api_core.exceptions import PermissionDenied, NotFound
import subprocess
import os

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
        print("Google Cloud credentials not found.")
        print("Would you like to authenticate interactively now? (y/n): ", end="")
        try:
            response = input().strip().lower()
            if response == 'y' or response == 'yes':
                print("Starting interactive Google Cloud authentication...")
                try:
                    print("Opening browser for Google Cloud authentication...")
                    print("Please complete the authentication in your browser.")
                    print("Press Enter when you have completed the authentication in the browser.")
                    input("Press Enter to continue after authentication...")

                    # Try to find gcloud in PATH first, then fallback to platform-specific paths
                    macos_gcloud = os.path.expanduser("~/Library/Application Support/cloud-code/installer/google-cloud-sdk/bin/gcloud")
                    windows_gcloud = r"C:\Users\AngusMcLauchlan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
                    gcloud_commands = [
                        ["gcloud", "auth", "application-default", "login"],
                        [macos_gcloud, "auth", "application-default", "login"],
                        [windows_gcloud, "auth", "application-default", "login"]
                    ]

                    success = False
                    for gcloud_cmd in gcloud_commands:
                        try:
                            print(f"Running: {' '.join(gcloud_cmd)}")
                            result = subprocess.run(
                                gcloud_cmd,
                                check=False,
                                # Don't capture output to allow interactive authentication
                            )

                            if result.returncode == 0:
                                print("Authentication completed successfully!")
                                success = True
                                break
                            else:
                                print(f"Authentication command failed with return code: {result.returncode}")
                        except FileNotFoundError:
                            print(f"gcloud command not found at: {gcloud_cmd[0]}")
                            continue
                        except Exception as cmd_error:
                            print(f"Error running gcloud command: {cmd_error}")
                            continue

                    if success:
                        print("Retrying Google Cloud access after authentication...")
                        # Retry the access test after successful authentication
                        return test_gcloud_access()
                    else:
                        print("Authentication failed.")
                        print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set or run 'gcloud auth application-default login' manually.")
                        return False

                except KeyboardInterrupt:
                    print("\nAuthentication cancelled by user.")
                    print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set or run 'gcloud auth application-default login' manually.")
                    return False
                except Exception as auth_error:
                    print(f"Error during authentication: {auth_error}")
                    print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set or run 'gcloud auth application-default login' manually.")
                    return False
            else:
                print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set or run 'gcloud auth application-default login' manually.")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled. Please ensure GOOGLE_APPLICATION_CREDENTIALS is set or run 'gcloud auth application-default login' manually.")
            return False
    except Exception as e:
        error_message = str(e)
        # Check if this is a reauthentication error or invalid grant (expired credentials)
        if ("Reauthentication is needed" in error_message or "invalid_grant" in error_message):
            print("Google Cloud authentication expired or invalid. Starting interactive authentication...")
            try:
                print("Opening browser for Google Cloud authentication...")

                # Try to find gcloud in PATH first, then fallback to platform-specific paths
                macos_gcloud = os.path.expanduser("~/Library/Application Support/cloud-code/installer/google-cloud-sdk/bin/gcloud")
                windows_gcloud = r"C:\Users\AngusMcLauchlan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
                gcloud_commands = [
                    ["gcloud", "auth", "application-default", "login"],
                    [macos_gcloud, "auth", "application-default", "login"],
                    [windows_gcloud, "auth", "application-default", "login"]
                ]

                success = False
                for gcloud_cmd in gcloud_commands:
                    try:
                        print(f"Running: {' '.join(gcloud_cmd)}")
                        result = subprocess.run(
                            gcloud_cmd,
                            check=False,
                            # Don't capture output to allow interactive authentication
                        )

                        if result.returncode == 0:
                            print("Authentication completed successfully!")
                            success = True
                            break
                        else:
                            print(f"Authentication command failed with return code: {result.returncode}")
                    except FileNotFoundError:
                        print(f"gcloud command not found at: {gcloud_cmd[0]}")
                        continue
                    except Exception as cmd_error:
                        print(f"Error running gcloud command: {cmd_error}")
                        continue

                if success:
                    print("Retrying Google Cloud access after authentication...")
                    # Retry the access test after successful authentication
                    return test_gcloud_access()
                else:
                    print("Authentication failed. Please run 'gcloud auth application-default login' manually.")
                    return False

            except KeyboardInterrupt:
                print("\nAuthentication cancelled by user.")
                return False
            except Exception as auth_error:
                print(f"Error during authentication: {auth_error}")
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
