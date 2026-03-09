#!/bin/bash
set -e

# Create data directory with correct ownership
mkdir -p /data
chown -R paperless:paperless /data

# Create consume directory with correct ownership  
mkdir -p /consume
chown -R paperless:paperless /consume

# Execute the fetcher as paperless user
exec su -s /bin/bash paperless -c "python -u /app/fetcher.py"
