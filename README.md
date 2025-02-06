# DuctTapeHook

A lightweight webhook utility that runs user-defined scripts with minimal dependencies.

The goals of DuctTapeHook are simplicity, minimal dependencies (only Python3), and ease of maintenance. It allows you to run user-defined shell scripts via a webhook endpoint, ideal for tasks like CI/CD deployments.

*For example*, it can be deployed on a cheap VPS to run CI/CD scripts and called by a Github Action after a build completes successfully.

## Installation

1. Clone the repo to the desired machine
2. Edit `config.env`
3. Set the `WEBHOOK_AUTH_TOKEN` to something long and random (ex. `openssl rand -hex 32`)
4. Set the `SCRIPT_PATH` to the _full path_ of the `./scripts/` directory
5. Run the `install.sh` script to install this as a systemd service on a linux system
6. Test with `test.sh`, update the token and you should see "hello world" and the date and time

## Configuration

Create subdirectories under `./scripts/`, each containing a `script.sh` file that will execute the desired task. Ensure the `script.sh` files are executable (ex. `chmod +x script.sh`) and include the correct shell header (ex. `#!/bin/bash`).

When a request with the correct auth token is received, the `Target` header is used to search for a matching subdirectory within `./scripts/` , sets it as the working directory, and finally runs the `script.sh`. Additional files can be included in the subdirectory next to the `script.sh` file.

## Security considerations

Running webhooks on the internet has inherent risks, as they need to be open to the internet to be useful. Some security already included within this DuctTapeHook:
- Bearer auth token
- Non-sepecific server header
- Path traversal attacks mitigated by only searching a specific directory

For secure use, users of DuctTapeHook must take some additional precautions:
- Only run this through an SSL-enabled reverse proxy 
- _Don't_ host app at `/webhook/`, as it is commonly scanned for vulnerabilities, pick a more obscure endpoint
- Run the service as another User and Group with limited privileges 
- Strongly consider leveraging whitelists for allowed remote IPs or CIDR ranges

Here are some ideas for future enhancements that would further improve security and functionality:
- [ ] Client verification using mutual TLS
- [ ] Message verification using HMAC signatures
- [ ] Timestamp verification of requests

## Nginx set up and configuration

For reference, this is a DigitalOcean guide to [install and configure Nginx](https://www.digitalocean.com/community/tutorials/how-to-install-nginx-on-ubuntu-22-04), another to [set up SSL in Nginx with Let's Encrypt](https://www.digitalocean.com/community/tutorials/how-to-secure-nginx-with-let-s-encrypt-on-ubuntu-22-04), and finally one to [configure Nginx as a reverse proxy](https://www.digitalocean.com/community/tutorials/how-to-configure-nginx-as-a-reverse-proxy-on-ubuntu-22-04).

Below is an example Nginx configuration snippet (ex. `/etc/nginx/sites-available/[your_domain]`) to set up reverse proxying and whitelisting of ips. 

```
server {
    ...

    location /[YOUR_WEBHOOK_URL]/ {
        proxy_pass http://localhost:2000;
        include proxy_params;

        allow [YOUR_IP];
        deny all;
    }

    ...
}

```

## Curl example

The command below will test the DuctTapeHook service once it is installed.

```
curl -H "Authorization: Bearer [YOUR_TOKEN_HERE]" \
     -H "Target: [SCRIPT_DIR_NAME]" \
     -X POST \
     https://[YOUR_SERVER_HERE]:2000/webhook/
```

## Github Actions example

For reference the below snippet can be included in a Github Action to send a request to a running DuctTapeHook service. The `WEBHOOK_TOKEN` secret need to be set within the repository's secrets, which can be found in Repo Settings -> Secrets and Variables -> Actions -> Repository Secrets.

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
