#!/bin/bash

SERVICE_NAME=ducttapehook
EXEC_PATH=$(readlink -f ./)/run_webhook.sh
 
if [ "$EUID" -ne 0 ]
  then echo "Please run as root"
  exit
fi

# check if service is active
if [ "active" == $(systemctl is-active $SERVICE_NAME) ]; then
    # restart the service
    echo "Restarting"
    systemctl restart $SERVICE_NAME
    echo "Service restarted"
else
    # create service file
    echo "Creating service file"
    cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=listens
After=network.target

[Service]
ExecStart=$EXEC_PATH
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
    # restart daemon, enable and start service
    echo "Reloading daemon and enabling service"
    systemctl daemon-reload 
    systemctl enable $SERVICE_NAME # remove the extension
    systemctl start $SERVICE_NAME
    echo "Service Started"
fi

exit 0