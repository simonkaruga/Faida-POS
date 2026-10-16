#!/usr/bin/env bash
# Update the cloud server: same steps and rollback as a counter update.
#   sudo ./update.sh faida-0.3.0.tar.gz
export FAIDA_SERVICE=faida-cloud FAIDA_ENV=/etc/faida/cloud.env \
  FAIDA_HEALTH_URL=http://127.0.0.1:8100/api/health FAIDA_UNITS=deploy/cloud
exec "$(dirname "$0")/../local/linux/update.sh" "$@"
