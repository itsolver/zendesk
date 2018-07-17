# Question
How can I export all my Zendesk data

# Answer
For all plans:
You can use the Zendesk Rest API endpoints along with your own custom scripts, or use these scripts:
 - Support: triggers, automations, macros, views, ticket fields, user fields, organisation fields, app installations using [backup_zendesk.py](https://github.com/itsolver/zendesk/blob/master/backup_zendesk.py).
  - Help Centre Content using [Felix Stubner's kBackup](https://support.zendesk.com/hc/en-us/community/posts/210927837). [kBackup source code](https://github.com/Fail2Reap/kBackup).
   - Help Centre Theme copied manually from Guide admin > Customise design.

For Professional and Enterprise customers:
You can [export data](https://support.zendesk.com/hc/en-us/articles/203662346-Exporting-data-to-a-JSON-CSV-or-XML-file-Professional-and-Enterprise-) as a CSV or XML.

# To do
## Add to backup script: 
- tickets, users and organizations.
- agent profile
- zendesk settings

## Add option to encrypt and move sensitive data to a private location
 - Tickets
 - People
 - Organizations
 
## Script as much as possible

## Automate backup schedule

## Create instructions on usage
