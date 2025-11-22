# DuctTapeHook

A lightweight webhook utility that runs user-defined scripts with minimal dependencies.

The goals of DuctTapeHook are simplicity, minimal dependencies (only Python3), and ease of maintenance. It allows you to run user-defined shell scripts via a webhook endpoint, ideal for tasks like CI/CD deployments.

*For example*, it can be deployed on a cheap VPS to run CI/CD scripts and called by a Github Action after a build completes successfully.

## Installation

1. Clone the repo to the desired machine
2. Copy `config.env.example` to `config.env`
3. Edit `config.env`:
   - Set `WEBHOOK_AUTH_TOKEN` to something long and random (ex. `openssl rand -hex 32`)
   - Set `SCRIPTS_PATH` to the _full path_ of the `./scripts/` directory
4. Run the `install.sh` script as root to install this as a systemd service
   - This will create a dedicated `webhook` user with restricted privileges
   - The service will run with security hardening enabled
5. Test with `test.sh` after updating the token - you should see "hello world" and the date

**Note**: The installer creates a system user named `webhook` that runs the service. You can customize the user/group by setting `SERVICE_USER` and `SERVICE_GROUP` environment variables before running `install.sh`.

## Configuration

Create subdirectories under `./scripts/`, each containing a `script.sh` file that will execute the desired task. Ensure the `script.sh` files are executable (ex. `chmod +x script.sh`) and include the correct shell header (ex. `#!/bin/bash`).

When a request with the correct auth token is received, the `Target` header is used to search for a matching subdirectory within `./scripts/` , sets it as the working directory, and finally runs the `script.sh`. Additional files can be included in the subdirectory next to the `script.sh` file.

## Security Features

DuctTapeHook includes comprehensive security measures:

**Authentication & Authorization:**
- Bearer token authentication with constant-time comparison (prevents timing attacks)
- Rate limiting (10 failed auth attempts per IP per minute)
- Environment variable sanitization with blocklists for dangerous variables

**System Security:**
- Runs as dedicated non-root user (`webhook`) with minimal privileges
- Systemd hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, etc.
- Path traversal protection (only searches configured scripts directory)
- Script execution timeout (5 minutes default)
- Request size limits (1MB max POST body)

**Operational Security:**
- Log rotation (10MB max, 5 backups)
- Restrictive log file permissions (0600)
- Graceful shutdown handling (SIGTERM/SIGINT)
- Non-specific server headers (doesn't leak version info)
- Health check endpoint at `/health` (no auth required)

## Additional Security Recommendations

For production deployments, implement these additional safeguards:
- **REQUIRED**: Run behind an SSL-enabled reverse proxy (Nginx/Apache)
- **REQUIRED**: Use IP whitelisting to restrict access to known sources
- Pick an obscure endpoint path (not `/webhook/` which is commonly scanned)
- Consider implementing mutual TLS for client verification
- Use HMAC signatures to verify request authenticity
- Monitor logs for suspicious activity

## Testing

Run the included test suite:

```bash
python3 test_main.py
```

Or with pytest (if installed):

```bash
python3 -m pytest test_main.py -v
```

## Health Check

You can verify the service is running without authentication:

```bash
curl http://localhost:2000/health
```

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
