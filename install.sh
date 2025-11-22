#!/bin/bash

SERVICE_NAME=ducttapehook
EXEC_PATH="$(readlink -f ./)/run_webhook.sh"
SERVICE_USER="${SERVICE_USER:-webhook}"
SERVICE_GROUP="${SERVICE_GROUP:-webhook}"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Validate that run_webhook.sh exists
if [ ! -f "$EXEC_PATH" ]; then
    echo "Error: run_webhook.sh not found at $EXEC_PATH"
    exit 1
fi

# Check if service is active
if [ "$(systemctl is-active "$SERVICE_NAME")" = "active" ]; then
    # Restart the service
    echo "Service is active. Restarting..."
    systemctl restart "$SERVICE_NAME"
    echo "Service restarted"
else
    # Create webhook user and group if they don't exist
    if ! id -u "$SERVICE_USER" > /dev/null 2>&1; then
        echo "Creating user: $SERVICE_USER"
        useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    fi

    # Create service file with security hardening
    echo "Creating service file"
    cat > /etc/systemd/system/"$SERVICE_NAME".service << EOF
[Unit]
Description=DuctTapeHook - Webhook service for running user-defined scripts
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
ExecStart=$EXEC_PATH
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$(dirname "$EXEC_PATH")
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF

    # Set ownership of the application directory to the service user
    APP_DIR="$(dirname "$EXEC_PATH")"
    echo "Setting ownership of $APP_DIR to $SERVICE_USER:$SERVICE_GROUP"
    chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$APP_DIR"

    # Restart daemon, enable and start service
    echo "Reloading daemon and enabling service"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"
    echo "Service started"
fi

# Show service status
echo ""
echo "Service status:"
systemctl status "$SERVICE_NAME" --no-pager

exit 0
