@echo off
title Dashcam Network Bridge
echo ==========================================
echo Starting Dashcam Network Bridge...
echo ==========================================
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
python usb_network_camera.py
pause
