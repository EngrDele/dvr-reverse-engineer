# Technical Protocol Specification: Generic Dashcam (WCM)

This document specifies the Wired Control Module (WCM) protocol used by the generic Android Dashcam over USB Mass Storage.

## 1. Transport Layer (SCSI-over-USB)

The device presents a standard USB Mass Storage interface (Bulk-Only Transport). Commands and data are exchanged using SCSI `READ(10)` commands.

- **VID/PID**: `0x1B3F:0x8301`
- **Interface**: 0 (Mass Storage)
- **Endpoints**: `0x02` (Bulk OUT), `0x81` (Bulk IN)

### Command Channel (Injection)
Commands are NOT written to the disk. Instead, they are encoded into the **Transfer Length** (number of blocks) of a SCSI Read command directed at **LBA 4851**.

### Response/Video Channel
Data is read starting at **LBA 4351**. One full JPEG frame is typically distributed across 600 sectors (307,200 bytes).

---

## 2. Command Encoding (Nibble Protocol)

A command packet is sent nibble-by-nibble (4 bits at a time).

1. **Header**: Host reads LBA 4851 with length **17 sectors** (start sequence).
2. **Payload**: For each byte in the command packet:
    - Host reads LBA 4851 with length = `(byte & 0x0F)` (Low nibble). *If value is 0, use 16.*
    - Host reads LBA 4851 with length = `(byte >> 4)` (High nibble). *If value is 0, use 16.*
3. **Footer**: Host reads LBA 4851 with length **18 sectors** (end sequence).

---

## 3. Packet Structure (WCM)

All commands follow this 10-byte header format:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0      | 2    | Header | `0x55AA` (LE) |
| 2      | 2    | Cmd ID | Command Identifier (LE) |
| 4      | 2    | Param | Command Parameter (LE) |
| 6      | 2    | Length | Data Payload Length (LE) |
| 8      | 2    | Checksum | `(CmdID + Param + Length - 0x55AB) & 0xFFFF` |

### Primary Command IDs

| ID | Name | Parameters |
|----|------|------------|
| 1  | StartRecord | 0 = Start streaming |
| 9  | GetStatus | Request status bitmask |
| 12 | SetDuration | 1/3/5 (minutes) |
| 19 | SetTime | Data: `[YY, MM, DD, HH, MM, SS]` |

---

## 4. Video Stream Properties

- **Container**: MJPEG (Standard JPEG frames concatenated).
- **Resolution**: 1280x720 (720p).
- **Frame Rate**: ~20 FPS.
- **Encoding**: H.264 (internal) → JPEG (output buffer).
- **Markers**: Look for `\xff\xd8` (SOI) and `\xff\xd9` (EOI).
