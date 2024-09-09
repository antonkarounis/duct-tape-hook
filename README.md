
# DuctTapeHook


This is a utility script that exposes a webhook endpoint, and runs user-defined scripts. The goal was to create a webhook utility that only requires Python3 installed, which is extremely common, and no additional libraries. 


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
- Security strongly suggested external to this app:
    - Only run this through an SSL-enabled reverse proxy
    - Set up a set of whitelisted remote IPs
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

## Sample curl for testing

```
curl -H "Authorization: Bearer [YOUR_TOKEN_HERE]" \
     -H "Target: [SCRIPT_DIR_NAME]" \
     -X POST \
     https://[YOUR_SERVER_HERE]:2000/webhook/
```

