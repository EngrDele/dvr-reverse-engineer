# DVR Network Bridge

A robust, cross-platform Python bridge that converts cheap USB Dashcams (specifically those enumerating as `CAR_DVR / USB-MSDC DISK A` with VID `0x1B3F` and PID `0x8301`) into fully standard network IP cameras.

These dashcams use a proprietary SCSI-over-USB protocol designed to be read by specific Android apps. This project reverse-engineers that protocol and serves the MJPEG frames over a standard HTTP interface with full NVR integration (Blue Iris, Home Assistant, Agent DVR).

## Features
- **Standard MJPEG Stream**: Serves video on `http://<IP>:9090/stream` (with correct boundaries and CORS headers).
- **Snapshot Support**: Fetch a single frame via `http://<IP>:9090/snapshot`.
- **ONVIF Auto-Discovery**: Built-in WS-Discovery server on port `3702` so standard NVRs can auto-detect the camera on your local network.
- **Linux Robustness**: Uses `sysfs` driver unbinding and `tmux` to ensure the SCSI stream works seamlessly on headless Linux and ARM boards (Raspberry Pi, Orange Pi, Ubuntu).

## Deployment

### Linux / Ubuntu / Raspberry Pi (Headless)
The easiest way to set this up on a headless Linux device is to use the included One-Command Setup script. This installs dependencies (Python, libusb, tmux), configures the USB handling, and sets up a `systemd` service to automatically start the bridge when the device boots.

```bash
git clone https://github.com/EngrDele/dvr-reverse-engineer.git
cd dvr-reverse-engineer
sudo bash linux_setup.sh
```

**Commands:**
- View Live Console: `sudo tmux attach-session -t dvr-bridge` (Press `Ctrl+B` then `D` to detach)
- View Logs: `sudo journalctl -u dvr-bridge -f`
- Stop Service: `sudo systemctl stop dvr-bridge`

### Windows (Desktop)
On Windows, you must install the `WinUSB` driver for the camera so that Python can communicate with it directly without the OS Mass Storage driver getting in the way.

1. Download and run [Zadig](https://zadig.akeo.ie/).
2. Select **Options > List All Devices**.
3. Select `USB-MSDC DISK A` (VID 1B3F, PID 8301).
4. Replace the driver with **WinUSB**.
5. Install dependencies and run:

```powershell
pip install pyusb opencv-python
python bridge/usb_network_camera.py
```

## Integration with NVRs

### Home Assistant
Add a new **Generic Camera** integration:
- Still Image URL: `http://<IP>:9090/snapshot`
- Stream Source URL: `http://<IP>:9090/stream`

### Blue Iris / Agent DVR
The camera should appear automatically in your network scan via ONVIF. If adding manually:
- IP/URL: `http://<IP>:9090/stream`
- Type: `MJPEG Stream`

## Technical Details (Reverse Engineering)
The camera exposes a standard USB Mass Storage interface (`ELEN1` firmware). By sending a specific sequence of SCSI Command Block Wrappers (CBW), the device is switched into streaming mode:
1. `GetStatus` (Command 9)
2. `SetDateTime` (Command 19)
3. `StartRecord` (Command 1)
4. Read frames using `Read10` SCSI commands.

For more information, see the `dvr_app/` folder which contains decompiled sources and research regarding the original `uCarDvr` APK behavior.