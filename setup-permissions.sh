#!/bin/bash
# This script needs to be run on the host machine to set executable permissions
# Run: chmod +x docker-entrypoint.sh

if [ ! -x "docker-entrypoint.sh" ]; then
    echo "Setting executable permission on docker-entrypoint.sh..."
    chmod +x docker-entrypoint.sh
    echo "✅ Permissions set"
else
    echo "✅ docker-entrypoint.sh is already executable"
fi
