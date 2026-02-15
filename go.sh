#!/bin/bash
# Usage:
#   ./go.sh                          Process all certs in inbox/
#   ./go.sh bls-cert.pdf             Process one specific cert
#   ./go.sh --tone casual            Change tone
#   ./go.sh bls-cert.pdf casual      Both

cd "$(dirname "$0")"
source venv/bin/activate
python generate.py "$@"
