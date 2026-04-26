# Generic DVR Dashcam Reverse Engineering & Network Bridge

This repository contains the results of a deep-dive reverse engineering project into a proprietary "Generic Android Dashcam" (commonly sold with the `uCarDVR` app). 

We have successfully deciphered the undocumented **SCSI-over-USB protocol** used to control the device and extract high-definition video frames without using the original Android application. This bridge allows you to turn a cheap $20 USB dashcam into a standard, headless IP camera compatible with any NVR software (like Frigate, Blue Iris, or Agent DVR).

---

## 🚀 The Breakthrough: SCSI Command Injection

The most interesting discovery of this project was how the manufacturer implemented a command channel on a standard "Mass Storage" device without writing a custom USB driver.

The device communicates by encoding 4-bit **nibbles** into the `Transfer Length` field of standard SCSI `READ(10)` commands directed at a specific disk offset (**LBA 4851**). By reading from the disk at various "magic" lengths, the host sends commands; the device then places JPEG video frames at a different offset (**LBA 4351**).

---

## 🛠️ Features

- **Headless Network Bridge**: Exposes the proprietary USB stream as standard MJPEG and ONVIF.
- **Auto-Discovery**: Support for WS-Discovery, allowing NVRs to find the camera automatically.
- **Self-Healing**: Automatic hardware reset (`dev.reset()`) if the camera's internal buffer stalls.
- **Cross-Platform**: Tested and working on **Windows 10/11** and **Ubuntu Linux**.
- **Web Dashboard**: Simple dark-mode UI to monitor the stream and system status.

---

## 📥 Installation

### Prerequisites
- Python 3.8+
- libusb-1.0 (included for Windows in `vendor/`)

### Windows Setup
1. **Driver Setup**: Use [Zadig](https://zadig.akeo.ie/) to replace the default "USB Mass Storage" driver with **WinUSB**. This allows Python to talk to the hardware directly.
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run**: Double-click `bridge/run_dashcam_bridge.bat`.

### Linux (Ubuntu) Setup
1. **Permissions**: Create a udev rule to allow non-root access to the camera:
   ```bash
   echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1b3f", ATTR{idProduct}=="8301", MODE="0666"' | sudo tee /etc/udev/rules.d/99-dashcam.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```
2. **Install dependencies**:
   ```bash
   sudo apt install python3-usb libusb-1.0-0
   pip3 install -r requirements.txt
   ```
3. **Run**:
   ```bash
   python3 bridge/usb_network_camera.py
   ```

---

## 📂 Repository Structure

- `bridge/`: Production-ready bridge scripts and launchers.
- `research/`: Detailed analysis reports, protocol specs, and lessons learned.
- `tools/`: Diagnostic utilities for hardware probing.
- `firmware/`: The original target APK for reference.
- `vendor/`: Pre-compiled drivers for Windows portability.

---

## 🎓 Lessons Learned
For a deep dive into the reverse engineering methodology used (JNI tracing, native library disassembly, and USB forensics), see [research/lessons_learned.md](research/lessons_learned.md).

---

## ⚖️ License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.