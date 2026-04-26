#!/usr/bin/env python3
"""
USB Camera Protocol Probe - Reverse Engineering Tool
Attempts to communicate with the dashcam (1B3F:8301) using SCSI Bulk-Only Transport
and custom command protocols to discover the streaming interface.
"""
import usb.core
import usb.util
import struct
import time
import sys

VID = 0x1B3F
PID = 0x8301
EP_OUT = 0x02  # BULK OUT
EP_IN = 0x81   # BULK IN
TIMEOUT = 2000

class USBCameraProbe:
    def __init__(self):
        self.dev = None
        self.tag = 1

    def connect(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            print("Device not found!")
            return False
        print(f"Connected to {VID:04x}:{PID:04x}")
        try:
            self.dev.set_configuration()
        except Exception as e:
            print(f"  set_configuration: {e}")
        try:
            cfg = self.dev.get_active_configuration()
            intf = cfg[(0, 0)]
            if self.dev.is_kernel_driver_active(intf.bInterfaceNumber):
                self.dev.detach_kernel_driver(intf.bInterfaceNumber)
            usb.util.claim_interface(self.dev, intf.bInterfaceNumber)
        except Exception as e:
            print(f"  claim_interface: {e}")
        return True

    def build_cbw(self, data_length, direction_in, lun, cb_data):
        """Build a SCSI Command Block Wrapper (CBW) - 31 bytes"""
        self.tag += 1
        flags = 0x80 if direction_in else 0x00
        cb_len = len(cb_data)
        # Pad CB to 16 bytes
        cb_padded = cb_data + b'\x00' * (16 - len(cb_data))
        cbw = struct.pack('<4sIIBBB', 
            b'USBC',           # dCBWSignature
            self.tag,          # dCBWTag
            data_length,       # dCBWDataTransferLength
            flags,             # bmCBWFlags
            lun,               # bCBWLUN
            cb_len             # bCBWCBLength
        ) + cb_padded
        return cbw

    def parse_csw(self, data):
        """Parse a SCSI Command Status Wrapper (CSW) - 13 bytes"""
        if len(data) < 13:
            return None
        sig, tag, residue, status = struct.unpack('<4sIIB', bytes(data[:13]))
        return {
            'signature': sig,
            'tag': tag,
            'residue': residue,
            'status': status,
            'valid': sig == b'USBS'
        }

    def scsi_command(self, cb_data, data_length=0, direction_in=True, lun=0):
        """Send a SCSI command and get response"""
        cbw = self.build_cbw(data_length, direction_in, lun, cb_data)

        # Send CBW
        try:
            self.dev.write(EP_OUT, cbw, timeout=TIMEOUT)
        except Exception as e:
            print(f"  CBW write failed: {e}")
            return None, None

        # Data phase
        data = None
        if data_length > 0 and direction_in:
            try:
                data = self.dev.read(EP_IN, data_length, timeout=TIMEOUT)
            except Exception as e:
                print(f"  Data read failed: {e}")

        # Read CSW
        try:
            csw_raw = self.dev.read(EP_IN, 13, timeout=TIMEOUT)
            csw = self.parse_csw(csw_raw)
        except Exception as e:
            print(f"  CSW read failed: {e}")
            csw = None

        return data, csw

    def test_inquiry(self):
        """Standard SCSI INQUIRY command"""
        print("\n=== SCSI INQUIRY (opcode 0x12) ===")
        # INQUIRY CDB: opcode=0x12, allocation_length=36
        cdb = bytes([0x12, 0x00, 0x00, 0x00, 0x24, 0x00])
        data, csw = self.scsi_command(cdb, data_length=36, direction_in=True)

        if data is not None:
            print(f"  Response ({len(data)} bytes): {bytes(data).hex()}")
            try:
                vendor = bytes(data[8:16]).decode('ascii', errors='replace').strip()
                product = bytes(data[16:32]).decode('ascii', errors='replace').strip()
                revision = bytes(data[32:36]).decode('ascii', errors='replace').strip()
                print(f"  Vendor:   '{vendor}'")
                print(f"  Product:  '{product}'")
                print(f"  Revision: '{revision}'")
            except:
                pass
        if csw:
            print(f"  CSW: valid={csw['valid']}, status={csw['status']}")
        return data is not None

    def test_read_capacity(self):
        """SCSI READ CAPACITY (10)"""
        print("\n=== SCSI READ CAPACITY (opcode 0x25) ===")
        cdb = bytes([0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        data, csw = self.scsi_command(cdb, data_length=8, direction_in=True)

        if data is not None:
            lba = struct.unpack('>I', bytes(data[0:4]))[0]
            block_size = struct.unpack('>I', bytes(data[4:8]))[0]
            print(f"  Last LBA: {lba}")
            print(f"  Block Size: {block_size}")
            print(f"  Capacity: {(lba + 1) * block_size / 1024:.1f} KB")
        if csw:
            print(f"  CSW: valid={csw['valid']}, status={csw['status']}")

    def test_vendor_commands(self):
        """Try vendor-specific SCSI commands that might switch to camera mode"""
        print("\n=== Testing Vendor-Specific Commands ===")

        # Try common vendor SCSI opcodes
        for opcode in [0xC0, 0xC1, 0xC2, 0xC6, 0xCA, 0xCB, 0xD0, 0xD8, 0xE7, 0xF0]:
            print(f"\n  --- Opcode 0x{opcode:02X} ---")

            # Try with various sub-commands matching the Java sendCommand2 IDs
            for subcmd in [0x00, 0x01, 0x09]:
                cdb = bytes([opcode, subcmd, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                try:
                    data, csw = self.scsi_command(cdb, data_length=512, direction_in=True)
                    if csw and csw['valid']:
                        status_str = "PASS" if csw['status'] == 0 else f"FAIL({csw['status']})"
                        data_str = bytes(data[:32]).hex() if data is not None else "None"
                        print(f"    subcmd=0x{subcmd:02X}: CSW={status_str}, data={data_str}")
                    elif data is not None:
                        print(f"    subcmd=0x{subcmd:02X}: Raw response: {bytes(data[:32]).hex()}")
                except usb.core.USBTimeoutError:
                    print(f"    subcmd=0x{subcmd:02X}: Timeout")
                    # Clear any stall
                    try:
                        self.dev.clear_halt(EP_IN)
                        self.dev.clear_halt(EP_OUT)
                    except:
                        pass
                except Exception as e:
                    err = str(e)
                    if len(err) > 60:
                        err = err[:60] + "..."
                    print(f"    subcmd=0x{subcmd:02X}: Error: {err}")
                    try:
                        self.dev.clear_halt(EP_IN)
                        self.dev.clear_halt(EP_OUT)
                    except:
                        pass

    def test_raw_read(self):
        """Try reading raw data from the device without sending commands first"""
        print("\n=== Raw Bulk Read Test ===")
        for size in [64, 512, 1024]:
            try:
                data = self.dev.read(EP_IN, size, timeout=1000)
                print(f"  Read {len(data)} bytes: {bytes(data[:32]).hex()}")
            except usb.core.USBTimeoutError:
                print(f"  Read {size} bytes: Timeout (no data)")
            except Exception as e:
                print(f"  Read {size} bytes: Error: {e}")
                try:
                    self.dev.clear_halt(EP_IN)
                except:
                    pass

    def test_custom_protocol(self):
        """Try the WCM custom protocol - command packets without SCSI CBW wrapping"""
        print("\n=== Custom Protocol Test (non-SCSI) ===")

        # The native lib has wcm_send_data and wcm_data_checksum
        # Try sending raw command packets that might match the WCM format
        # Based on sendCommand2(cmd_id, param1, param2, data) from Java

        for cmd_id in [9, 29, 240]:  # 9=GetStatus, 29=GetFirmware, 240=GetSSID
            # Try different packet formats
            # Format 1: Simple [cmd_id, param1_lo, param1_hi, param2_lo, param2_hi]
            pkt1 = struct.pack('<BHHH', cmd_id, 0, 0, 0) + b'\x00' * 7
            # Format 2: [header, cmd_id, length, data...]
            pkt2 = struct.pack('<BBH', 0xAA, cmd_id, 0) + b'\x00' * 12
            # Format 3: Little-endian cmd as 32-bit
            pkt3 = struct.pack('<IIII', cmd_id, 0, 0, 0)
            # Format 4: With magic header
            pkt4 = b'\x55\xAA' + struct.pack('<HII', cmd_id, 0, 0) + b'\x00' * 2

            for fmt_name, pkt in [("fmt1", pkt1), ("fmt2", pkt2), ("fmt3", pkt3), ("fmt4", pkt4)]:
                try:
                    self.dev.write(EP_OUT, pkt, timeout=1000)
                    time.sleep(0.1)
                    data = self.dev.read(EP_IN, 512, timeout=1000)
                    print(f"  cmd={cmd_id} {fmt_name}: Got {len(data)}B: {bytes(data[:32]).hex()}")
                except usb.core.USBTimeoutError:
                    pass  # Expected for most formats
                except Exception as e:
                    try:
                        self.dev.clear_halt(EP_IN)
                        self.dev.clear_halt(EP_OUT)
                    except:
                        pass

        print("  (No response from custom packets - protocol may require SCSI wrapping)")

    def run_all_tests(self):
        if not self.connect():
            return

        self.test_raw_read()
        scsi_works = self.test_inquiry()
        if scsi_works:
            self.test_read_capacity()
            self.test_vendor_commands()
        else:
            self.test_custom_protocol()

        print("\n=== Done ===")

if __name__ == '__main__':
    probe = USBCameraProbe()
    probe.run_all_tests()
