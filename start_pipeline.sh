#!/bin/bash
# Start the pipeline voice agent (web services) on port 5050.
# Usage: ./start_pipeline.sh <public-base-url>
# e.g. ./start_pipeline.sh https://abc123.ngrok-free.app
# The public URL is the tunnel address Twilio reaches. The server uses it
# to build the wss:// stream URL in the TwiML it returns to Twilio.
set -e
cd "$(dirname "$0")"
PUBLIC_BASE_URL="${1:-${PUBLIC_BASE_URL:-}}"
if [ -z "$PUBLIC_BASE_URL" ]; then
  echo "Usage: $0 <public-base-url>  (e.g. https://abc123.ngrok-free.app)" >&2
  exit 1
fi
export PUBLIC_BASE_URL
export BUSINESS_MODULE="${BUSINESS_MODULE:-webservices}"
exec ./venv/bin/uvicorn pipeline_server:app --host 0.0.0.0 --port 5050
