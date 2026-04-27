#!/bin/bash
# uCarDVR / USB-MSDC DISK A - Linux One-Command Setup
# This script installs all required dependencies and creates a systemd service
# that automatically runs the DVR Network Bridge inside a tmux session on boot.

set -e

echo "=========================================================="
echo "      DVR Network Bridge — Linux Auto-Setup Script        "
echo "=========================================================="

if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (use sudo ./linux_setup.sh)"
  exit 1
fi

echo "[1/4] Installing dependencies (python3, pip, libusb, tmux, opencv)..."
apt-get update
apt-get install -y python3 python3-pip python3-usb python3-opencv tmux

echo "[2/4] Installing Python requirements..."
pip3 install pyusb --break-system-packages || pip3 install pyusb

echo "[3/4] Installing Bridge Script to /usr/local/bin..."
cp bridge/usb_network_camera.py /usr/local/bin/dvr_bridge.py
chmod +x /usr/local/bin/dvr_bridge.py

echo "[4/4] Creating systemd service..."
cat << 'EOF' > /etc/systemd/system/dvr-bridge.service
[Unit]
Description=DVR Network Camera Bridge (tmux)
After=network.target

[Service]
Type=forking
# Start a detached tmux session named 'dvr-bridge'
ExecStart=/usr/bin/tmux new-session -d -s dvr-bridge 'python3 -u /usr/local/bin/dvr_bridge.py | tee /var/log/dvr_bridge.log'
# Stop the tmux session gracefully
ExecStop=/usr/bin/tmux kill-session -t dvr-bridge
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dvr-bridge.service
systemctl restart dvr-bridge.service

echo "=========================================================="
echo "Setup Complete!"
echo "The DVR Bridge is now running in the background via tmux."
echo ""
echo "To view the stream, go to:  http://<this-device-ip>:9090/"
echo "To view the live console:   tmux attach-session -t dvr-bridge"
echo "To view the service logs:   journalctl -u dvr-bridge -f"
echo "=========================================================="
