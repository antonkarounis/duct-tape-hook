
# DuctTapeHook


This is a utility script that exposes a webhook endpoint, and runs user-defined scripts. The goal is to:

- host a simple webhook http endpoint
- with minimal dependencies - only require Python3 installed, which is extremely common, and no additional libraries
- easy maintenance - after setup just drop in new scripts to be run in sub-directories

It is (I am) biased towards an Ubuntu-flavored Linux system with Systemd and Bash. *For example*, it can be used on a cheap VPS as a webhook endpoint to run CI/CD deploy scripts after a Github Action build completes successfully.


## Installation

1. Clone or grab the zip of the repo on the desired machine
2. Rename `example.config.env` to `config.env`
3. Set the `WEBHOOK_AUTH_TOKEN` in the config to something long and random
4. Set the `SCRIPT_PATH` to the full path to the script directory
5. Run the `install.sh` script to install this as a systemd service on a linux system

## Configuration

When a request with the correct token comes in, the `target` header is mapped to a directory within the `SCRIPT_PATH`, and a `script.sh` within that directory is run. Make sure to `chmod +x script.sh` the file and include the correct shell header (ex. `#!/bin/bash`).


## Security considerations

This script should only be run behind an SSL enabled reverse proxy for minimum security needs, in addition to the required auth token. Additionally one *should* whitelist allowed remote IPs or ranges in their reverse proxy for increased security.

- Security within this app:
    - Bearer auth token
    - Removed server header
- Security strongly suggested external to this app:
    - Only run this through an SSL-enabled reverse proxy
    - _Don't_ host app at `/webhook/`, pick something random
    - Leverage whitelists for allowed remote IPs or CIDR ranges
- Potential future improvements:
    - [ ] Client verification using mutual TLS
    - [ ] Message verification using HMAC signatures
    - [ ] Timestamp verification of requests


## NGINX example configuration
This is an exmaple `sites-available` snippet to set up reverse proxying and whitelisting of ips

```
server {

    ...
    ...

    location /webhook/ {
        proxy_pass http://localhost:2000;
        include proxy_params;

        allow [YOUR_IP];
        deny all;
    }

    ...
    ...
}

```

## Curl example

```
curl -H "Authorization: Bearer [YOUR_TOKEN_HERE]" \
     -H "Target: [SCRIPT_DIR_NAME]" \
     -X POST \
     https://[YOUR_SERVER_HERE]:2000/webhook/
```

## Github Actions example

Need to set the two env variables below, as well as the `WEBHOOK_TOKEN` in Repo Settings -> Secrets and Variables -> Actions -> Repository Secrets,

```
name: Fire webhook

on: workflow_dispatch

env:
  WEBHOOK_SERVER: [YOUR SERVER NAME]
  WEBHOOK_TARGET: [YOUR TARGET DIR]

jobs:
  build:
    runs-on: ubuntu-latest
        
    steps:
      
    - name: fire webhook
      run: |
        curl -H "Authorization: Bearer ${{ secrets.WEBHOOK_TOKEN }}" -H "Target: ${{ env.WEBHOOK_TARGET }}" -X POST ${{ env.WEBHOOK_SERVER }}
```