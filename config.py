# To do
# 1. Set values for your zendesk_subdomain, zendesk_user and destination_folder.
# 2. Run `python3 config.py`` to set keyring with your credentials. This is more secure than leaving credentials in plain sight.
zendesk_subdomain = "itsolver.zendesk.com"
zendesk_user = "angus@itsolver.net/token"
# Returns data that changed since the start time. See Usage Notes above.
# to get epoch time on mac terminal use e.g. ``date -j -f "%d-%B-%y" 19-FEB-12 +%s``
start_time = "1329575862"

# Start Mac config
# import keyring
# import getpass
# zendesk_secret = keyring.get_password("system", zendesk_user)

# if zendesk_secret is None:
#     zendesk_secret = getpass.getpass('Zendesk password or api_token: ')
#     keyring.set_password("system", zendesk_user, zendesk_secret)

# destination_folder = "/Volumes/GoogleDrive/My Drive/1. Management/Zendesk/Backups"

# End Mac config

# Start Windows config
destination_folder = "G:\Shared drives\Business\Zendesk\Backups"
# End Windows config

print("Config loaded!")