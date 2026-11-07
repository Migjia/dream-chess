#!/usr/bin/env bash
# Survey the YAM station's NUC. Read-only: it moves nothing, opens no camera stream,
# changes no files, and doesn't print any keys.
#
#   bash tools/inspect_station.sh 2>&1 | tee station_report.txt
#
# Read the report before sharing it: it can include file paths and network names.

section() { printf '\n===== %s =====\n' "$1"; }

section "machine"
hostname; uname -sr; grep PRETTY_NAME /etc/os-release 2>/dev/null; whoami
df -h "$HOME" | tail -1
free -h | sed -n 2p

section "python"
for py in python3 python3.10 python3.11 python3.12; do
    command -v "$py" >/dev/null && echo "$py: $("$py" --version 2>&1)"
done
command -v uv conda 2>/dev/null

section "dream tools"
command -v dreamcli || echo "dreamcli not on PATH"
python3 -m pip list 2>/dev/null | grep -iE 'dream|i2rt|realsense|opencv|numpy|chess'
if [ -f "$HOME/.dreamlabs/credentials" ]; then
    echo "credentials file: present"
    # Names only, so the API key is never printed.
    cut -d= -f1 "$HOME/.dreamlabs/credentials"
else
    echo "credentials file: missing"
fi
[ -n "${DREAM_API_KEY:-}" ] && echo "DREAM_API_KEY: set" || echo "DREAM_API_KEY: not set"

section "station config files"
find "$HOME" -maxdepth 4 \( -name 'station*.yaml' -o -name 'station*.yml' -o -name '*.arm' -o -name 'arm*.yaml' \) \
    -not -path '*/.cache/*' 2>/dev/null | head -20

section "what's running that may hold the arms or cameras"
ps -eo pid,user,etime,cmd | grep -iE 'dream|realsense|i2rt|yam|python' | grep -v grep | head -20

section "cameras"
command -v rs-enumerate-devices >/dev/null && rs-enumerate-devices -s 2>/dev/null
lsusb 2>/dev/null | grep -iE 'intel|realsense'
ls /dev/video* 2>/dev/null | wc -l | xargs echo "video devices:"

section "arm connections (CAN)"
ip -brief link show type can 2>/dev/null || true
ls /sys/class/net | grep -iE 'can' || echo "no CAN interfaces found"

section "network to Dream"
for host in api.dreamlabs.ai platform.dreamlabs.ai; do
    code=$(curl -s -o /dev/null -m 8 -w '%{http_code} in %{time_total}s' "https://$host" 2>/dev/null)
    echo "$host: ${code:-unreachable}"
done

section "tools"
command -v git gh stockfish tmux 2>/dev/null
