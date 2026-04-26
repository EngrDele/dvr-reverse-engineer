# Reverse Engineering Lessons Learned: USB Dashcam

This document serves as a master reference for the methodologies, techniques, and specific "gotchas" discovered while reverse-engineering the proprietary `uCarDVR` USB dashcam. These lessons are highly applicable to any future IoT or undocumented hardware reverse engineering tasks.

## 1. Initial Reconnaissance: Finding the Attack Surface

When confronted with a "black box" USB device that requires a proprietary Android app, your primary goal is to find the communication channel between the App and the Hardware.

**Key Techniques Used:**
- **USB Packet Capture (Wireshark/USBPcap):** We initially captured USB traffic but saw standard "Mass Storage" SCSI reads/writes. This was confusing because there were no UVC (USB Video Class) video endpoints.
- **APK Decompilation (`JADX`):** Decompiling the APK revealed how the app searched for the camera: it didn't look for a USB device, it looked for a mounted USB storage volume containing a specific file (`elen1`).
- **Lesson:** Hardware developers often repurpose existing, stable USB classes (like Mass Storage) to avoid writing custom Windows/Linux drivers. If a device mounts as a flash drive but streams video, it is using a file-based or LBA-based buffer.

## 2. JNI and Native Code Tracing

Proprietary processing is almost always hidden in native C/C++ libraries (`.so` files) because it is harder to decompile and more performant for video.

**Key Techniques Used:**
- **Finding the JNI Bridge:** In the Java code, we found `public static native int sendCommand2(...)`. We tracked this to `libstream_decoder.so`.
- **Static Analysis (Objdump/Ghidra/Strings):** By dumping the dynamic symbols (`objdump -T`) and read-only strings (`strings`) of the `.so` file, we identified the internal C functions handling the commands.
- **The Breakthrough:** We discovered strings like `WCM` (Wired Control Module) and references to SCSI command blocks (`CBW`/`CSW`). This proved the native library was bypassing the filesystem and sending raw SCSI commands directly to the block device.

> [!TIP]
> **Reusable Skill:** When analyzing Android hardware apps, search for `native` keyword in Java. Then use `readelf -d` to see library dependencies, and `strings libname.so | grep -i <command_name>` to match Java constants to C strings.

## 3. Deciphering the "Mass Storage" Command Injection

The most brilliant (and frustrating) part of the manufacturer's design was how they sent commands without writing to the disk.

**The Mechanism:**
- The host sends a standard SCSI `READ(10)` command to a specific Logical Block Address (LBA `4851`).
- Instead of the `Transfer Length` representing how much data to read, the native library encoded **protocol nibbles** (4-bit chunks of the command packet) into the `Transfer Length` field itself.
- **Lesson:** In embedded reverse engineering, data can be encoded in *metadata* or *control fields* (like read lengths, port numbers, or timing intervals) rather than the payload itself.

## 4. Hardware Instability & The 10-Second Rule

Embedded hardware firmware is often incredibly fragile. While building the Python script, the stream would reliably die after exactly 10 seconds (200 frames).

**The Trap:**
- The Python script was catching USB `Pipe Errors` silently and simply retrying. Because the errors were swallowed, the script looked like it was waiting for frames, but the USB endpoint was permanently halted.
- The 10-second limit was a hardcoded hardware buffer timeout; the native Android app used an undocumented sequence to keep it alive.

**The Solution (`dev.reset()`):**
- Rather than spending weeks trying to perfectly emulate the Android app's timing in a virtual environment, we used a sledgehammer: **USB Hardware Reset**.
- By catching the stall and issuing `dev.reset()` in `pyusb`, we forced the Windows USB subsystem to physically drop and re-enumerate the device. Re-sending the initialization sequence immediately revived the stream seamlessly.

> [!IMPORTANT]
> **Reusable Skill:** If proprietary hardware hangs or requires a magic "keep-alive" you cannot easily decipher, do not fight the firmware. Treat the hang as a predictable state and build a robust, fast automated reset/recovery loop in your software. Resilience often beats perfection.

## 5. Summary Checklist for Future Projects

1. **Decompile the App First:** Don't stare at Wireshark blindly. Use `jadx` to read the Java layer; it will give you the vocabulary (command IDs, file names, API endpoints) to understand the packet captures.
2. **Follow the `native` Keyword:** Map JNI functions to the `.so` symbols.
3. **Question the Transport Layer:** If a device doesn't use the expected standard (e.g., UVC for video), check if it's tunneling data through something else (Audio, Mass Storage, HID).
4. **Build Self-Healing Code:** Wrap all hardware I/O in aggressive `try/except` blocks. If the hardware locks up, reset the bus, clear the halts, and re-initialize. 
