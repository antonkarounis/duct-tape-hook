#!/bin/bash

cd "$(dirname "$0")"

set -a
source ./config.env
set +a

python3 main.py