#!/bin/bash

curl -H "Content-Type: application/json" \
     -H "X-Github-Event: push" \
     -X POST \
     -d '{"ref":"refs/heads/main"}' \
     http://localhost:5000

echo    