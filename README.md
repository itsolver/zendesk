# Question
How can I export all my Zendesk data

# Answer
For all plans:
You can use the Zendesk Rest API endpoints along with your own custom scripts, or use these scripts:
 - Support: tickets, users, organizations, triggers, automations, macros, views, ticket fields, user fields, organisation fields, app installations using [backup_zendesk.py](https://github.com/itsolver/zendesk/blob/master/backup_zendesk.py).
  - Help Centre Content using [Felix Stubner's kBackup](https://support.zendesk.com/hc/en-us/community/posts/210927837). [kBackup source code](https://github.com/Fail2Reap/kBackup).
   - Help Centre Theme copied manually from Guide admin > Customise design.

For Professional and Enterprise customers:
You can [export data](https://support.zendesk.com/hc/en-us/articles/203662346-Exporting-data-to-a-JSON-CSV-or-XML-file-Professional-and-Enterprise-) as a CSV or XML.

# Installation
1. Create and activate a new virtual environment

**MacOS / Unix**

```
python -m venv env
source /.venv/bin/activate
```

**Windows (PowerShell)**

```
python -m venv env
.venv\Scripts\activate.ps1
```

2. Install requirements:

```
pip install -r requirements.txt
```

# Usage
Customize variables in config.py 



Run backup:
```
python backup_zendesk.py
```

# To do
## Fix issue
- script stuck in loop on downloading latest ticket "Rate limited! Please wait."

## Add to backup script: 
- agent profile
- zendesk settings
 
## Script as much as possible

## Automate backup schedule

## Create instructions on usage
