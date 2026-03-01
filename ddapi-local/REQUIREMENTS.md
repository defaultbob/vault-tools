Create a way to sync data from Veeva Vault to a local sqllite database via Direct Data API.

## Must
* Seed and sync data to a local sqllite database
* if no db detected sync from full file
* Uses a local file, ignored from git to provide username and password credential
* if db exists keep up to date with 15 minute incremental files
* database must continue to be usable during syncing (after initial seed)
* Be able to be set as a CRON job on mac
* import/copy and use https://github.com/veeva/Vault-Direct-Data-API-Accelerators code
* Include a readme for how to install with uv and use
* include instructions for how to set up as CRON job and simple script
* Must create logs for debugging

