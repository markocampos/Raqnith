#!/usr/bin/env bash
# Raqnith root restart shortcut
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/infra/restart.sh" "$@"
