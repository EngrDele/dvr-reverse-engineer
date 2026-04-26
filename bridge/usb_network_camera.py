#!/usr/bin/env python3
"""
USB CAR DVR — Network Camera Bridge
Single-file, proven implementation.

Features:
  - Live OpenCV display window
  - MJPEG HTTP stream on port 9090 (any browser/NVR can connect)
  - Snapshot endpoint
  - ONVIF WS-Discovery (NVR auto-detection)

Based on v21 (proven 20 FPS capture).
Run: python usb_network_camera.py
"""
import usb.core
import usb.util
import usb.backend.libusb1
import struct
import time
import threading
import socket
import uuid
import json
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

# ═══════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════
VID = 0x1B3F
PID = 0x8301
EP_OUT = 0x02
EP_IN = 0x81
TIMEOUT = 5000

WCM_LBA = 4851
RESP_LBA = 4351

HTTP_PORT = 9090
ONVIF_PORT = 9092

# ═══════════════════════════════════════════════════════════
#  Shared State (simple globals — no complex threading)
# ═══════════════════════════════════════════════════════════
current_frame = None       # Latest JPEG bytes
frame_lock = threading.Lock()
frame_count = 0
fps_value = 0.0

# ═══════════════════════════════════════════════════════════
#  USB / SCSI / WCM  (proven v21 code)
# ═══════════════════════════════════════════════════════════
tag_counter = [0]

def cbw(data_len, cdb):
    tag_counter[0] += 1
    pad = (cdb + b'\x00' * 16)[:16]
    return struct.pack('<4sIIBBB', b'USBC', tag_counter[0], data_len,
                       0x80, 0, len(cdb)) + pad

def scsi_read(dev, lba, nb):
    total = nb * 512
    cdb = struct.pack('>BBIBHB', 0x28, 0x00, lba, 0x00, nb, 0x00)
    dev.write(EP_OUT, cbw(total, cdb), timeout=TIMEOUT)
    data = bytes(dev.read(EP_IN, total, timeout=TIMEOUT))
    try:
        dev.read(EP_IN, 13, timeout=TIMEOUT)  # CSW
    except:
        pass
    return data

def clear_halt(dev):
    try: dev.clear_halt(EP_IN)
    except: pass
    try: dev.clear_halt(EP_OUT)
    except: pass

def wcm_send(dev, cmd_id, param1=0, data=None):
    data_len = len(data) if data else 0
    chk = (cmd_id + param1 + data_len - 0x55AB) & 0xFFFF
    wcm = struct.pack('<HHHHH', 0xAA55, cmd_id, param1, data_len, chk)
    if data:
        wcm += bytes(data[:data_len])
    encode_buf = wcm[2:2 + 4 + data_len]

    scsi_read(dev, WCM_LBA, 17)
    for byte_val in encode_buf:
        lo = byte_val & 0x0F
        hi = (byte_val >> 4) & 0x0F
        scsi_read(dev, WCM_LBA, lo if lo else 16)
        scsi_read(dev, WCM_LBA, hi if hi else 16)
    scsi_read(dev, WCM_LBA, 18)

def capture_one_frame(dev):
    """Read full elen1 area (600 blocks = 307200 bytes) and extract JPEG"""
    full_data = bytearray()
    for chunk in range(0, 600, 64):
        nb = min(64, 600 - chunk)
        try:
            d = scsi_read(dev, RESP_LBA + chunk, nb)
            full_data.extend(d)
        except Exception as e:
            break  # Break instead of return None. The JPEG might already be in full_data.

    soi = full_data.find(b'\xff\xd8')
    if soi == -1:
        return None
    eoi = full_data.find(b'\xff\xd9', soi + 2)
    if eoi == -1:
        return None

    # Extraneous bytes after FFD9 don't matter, just return the exact JPEG buffer
    return bytes(full_data[soi:eoi + 2])

# ═══════════════════════════════════════════════════════════
#  HTTP Server (MJPEG stream + snapshot + web UI)
# ═══════════════════════════════════════════════════════════
class CamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Suppress HTTP logs

    def do_GET(self):
        if self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type',
                             'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            prev = None
            try:
                while True:
                    with frame_lock:
                        f = current_frame
                    if f and f is not prev:
                        prev = f
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(b'Content-Length: ' + str(len(f)).encode() + b'\r\n\r\n')
                        self.wfile.write(f)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                    time.sleep(0.05)
            except:
                pass

        elif self.path.startswith('/snapshot'):
            with frame_lock:
                f = current_frame
            if f:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(f)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(f)
            else:
                self.send_error(503)

        elif self.path == '/status':
            s = json.dumps({'connected': current_frame is not None,
                            'fps': round(fps_value, 1),
                            'frames': frame_count}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(s)))
            self.end_headers()
            self.wfile.write(s)

        elif self.path in ('/', '/index.html'):
            html = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>USB DVR Network Camera</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a1a;color:#ddd;font-family:'Segoe UI',sans-serif;
  display:flex;flex-direction:column;align-items:center;padding:20px;min-height:100vh}
h1{font-size:1.4em;color:#00d4ff;margin-bottom:8px;text-shadow:0 0 20px rgba(0,212,255,0.3)}
.bar{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);
  border-radius:8px;padding:6px 16px;margin-bottom:12px;font-size:0.8em;display:flex;gap:16px}
.bar .on{color:#0f0} .bar .off{color:#f00}
.wrap{position:relative;border-radius:10px;overflow:hidden;
  box-shadow:0 0 40px rgba(0,0,0,0.5);border:1px solid rgba(255,255,255,0.08)}
#cam{display:block;max-width:95vw;max-height:72vh;background:#000}
.ov{position:absolute;top:8px;left:10px;background:rgba(0,0,0,0.7);color:#0f0;
  padding:3px 8px;border-radius:4px;font:0.7em monospace}
.rec{color:#f00;animation:b 1s infinite}@keyframes b{50%{opacity:.3}}
.btns{margin:12px 0;display:flex;gap:8px}
.btn{background:rgba(255,255,255,0.06);color:#aaa;border:1px solid rgba(255,255,255,0.1);
  padding:8px 16px;border-radius:6px;cursor:pointer;font-size:0.8em;transition:.2s}
.btn:hover{background:rgba(0,212,255,0.15);color:#00d4ff;border-color:#00d4ff33}
.info{font-size:0.7em;color:#444;margin-top:auto;padding-top:16px}
code{background:rgba(255,255,255,0.08);padding:2px 5px;border-radius:3px;color:#888}
</style></head><body>
<h1>&#128249; USB DVR — Network Camera</h1>
<div class="bar"><span id="s">Connecting...</span>
<span>&#127909; <span id="fps">0</span> FPS</span>
<span>&#128247; <span id="fc">0</span> frames</span></div>
<div class="wrap">
<img id="cam" alt="Live"><div class="ov"><span class="rec">● REC</span> <span id="fov">0</span> FPS</div>
</div>
<div class="btns">
<button class="btn" onclick="window.open('/snapshot?'+Date.now())">&#128247; Snapshot</button>
<button class="btn" onclick="toggleMode()">&#128260; <span id="ml">MJPEG mode</span></button>
<button class="btn" onclick="document.querySelector('.wrap').requestFullscreen()">&#128306; Fullscreen</button>
</div>
<div class="info">
Stream: <code>http://HOST:""" + str(HTTP_PORT) + """/stream</code> &nbsp;
Snap: <code>http://HOST:""" + str(HTTP_PORT) + """/snapshot</code> &nbsp;
ONVIF: <code>auto-discovered on port """ + str(ONVIF_PORT) + """</code>
</div>
<script>
let mode='poll',t;
function poll(){t=setInterval(()=>{
  let i=new Image();i.onload=()=>document.getElementById('cam').src=i.src;
  i.src='/snapshot?'+Date.now()},150)}
function mjpeg(){document.getElementById('cam').src='/stream?'+Date.now()}
function toggleMode(){
  if(mode==='poll'){clearInterval(t);mjpeg();mode='mjpeg';
    document.getElementById('ml').textContent='Polling mode'}
  else{mode='poll';poll();document.getElementById('ml').textContent='MJPEG mode'}}
poll();
setInterval(async()=>{try{let r=await fetch('/status'),s=await r.json();
  document.getElementById('s').innerHTML=s.connected?
    '<span class="on">● Connected</span>':'<span class="off">● Disconnected</span>';
  document.getElementById('fps').textContent=s.fps;
  document.getElementById('fc').textContent=s.frames;
  document.getElementById('fov').textContent=s.fps}catch(e){}},2000);
</script></body></html>"""
            b = html.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self.send_error(404)

# ═══════════════════════════════════════════════════════════
#  ONVIF WS-Discovery
# ═══════════════════════════════════════════════════════════
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def onvif_discovery_thread():
    """Listen for WS-Discovery probes and respond."""
    DEVICE_UUID = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'usb-dvr-cam'))
    ip = get_local_ip()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 3702))
        mreq = struct.pack('4sL', socket.inet_aton('239.255.255.250'),
                           socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)
        print("  ONVIF Discovery: listening on 239.255.255.250:3702")
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                msg = data.decode('utf-8', errors='replace')
                if 'Probe' in msg:
                    xaddr = 'http://{}:{}/onvif'.format(ip, ONVIF_PORT)
                    resp = (
                        '<?xml version="1.0"?>'
                        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
                        ' xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
                        ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
                        ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
                        '<s:Body><d:ProbeMatches><d:ProbeMatch>'
                        '<a:EndpointReference><a:Address>urn:uuid:{}</a:Address>'
                        '</a:EndpointReference>'
                        '<d:Types>dn:NetworkVideoTransmitter</d:Types>'
                        '<d:Scopes>onvif://www.onvif.org/Profile/Streaming'
                        ' onvif://www.onvif.org/name/USB-DVR-CAM</d:Scopes>'
                        '<d:XAddrs>{}</d:XAddrs>'
                        '<d:MetadataVersion>1</d:MetadataVersion>'
                        '</d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>'
                    ).format(DEVICE_UUID, xaddr)
                    sock.sendto(resp.encode(), addr)
            except socket.timeout:
                continue
            except:
                pass
    except Exception as e:
        print("  ONVIF Discovery error: {}".format(e))

def onvif_service_thread():
    """Minimal ONVIF SOAP service for GetStreamUri etc."""
    ip = get_local_ip()

    class ONVIFHandler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            cl = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(cl).decode('utf-8', errors='replace')
            env = '<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><s:Body>{}</s:Body></s:Envelope>'
            if 'GetStreamUri' in body:
                r = env.format('<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>http://{}:{}/stream</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>'.format(ip, HTTP_PORT))
            elif 'GetSnapshotUri' in body:
                r = env.format('<trt:GetSnapshotUriResponse><trt:MediaUri><tt:Uri>http://{}:{}/snapshot</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>'.format(ip, HTTP_PORT))
            elif 'GetProfiles' in body:
                r = env.format('<trt:GetProfilesResponse><trt:Profiles token="p1" fixed="true"><tt:Name>MainStream</tt:Name><tt:VideoEncoderConfiguration token="v1"><tt:Encoding>JPEG</tt:Encoding><tt:Resolution><tt:Width>1280</tt:Width><tt:Height>720</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></trt:Profiles></trt:GetProfilesResponse>')
            elif 'GetDeviceInformation' in body:
                r = env.format('<tds:GetDeviceInformationResponse><tds:Manufacturer>Generalplus</tds:Manufacturer><tds:Model>USB-DVR-CAM</tds:Model><tds:FirmwareVersion>1.0</tds:FirmwareVersion><tds:SerialNumber>GP1B3F8301</tds:SerialNumber><tds:HardwareId>GP-1B3F</tds:HardwareId></tds:GetDeviceInformationResponse>')
            elif 'GetSystemDateAndTime' in body:
                t = time.gmtime()
                r = env.format('<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:UTCDateTime><tt:Time><tt:Hour>{}</tt:Hour><tt:Minute>{}</tt:Minute><tt:Second>{}</tt:Second></tt:Time><tt:Date><tt:Year>{}</tt:Year><tt:Month>{}</tt:Month><tt:Day>{}</tt:Day></tt:Date></tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>'.format(t.tm_hour, t.tm_min, t.tm_sec, t.tm_year, t.tm_mon, t.tm_mday))
            else:
                r = env.format('<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media><tt:XAddr>http://{}:{}/onvif</tt:XAddr></tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>'.format(ip, ONVIF_PORT))
            rb = r.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/soap+xml')
            self.send_header('Content-Length', str(len(rb)))
            self.end_headers()
            self.wfile.write(rb)

    server = HTTPServer(('0.0.0.0', ONVIF_PORT), ONVIFHandler)
    print("  ONVIF Service:   http://{}:{}/onvif".format(ip, ONVIF_PORT))
    server.serve_forever()

# ═══════════════════════════════════════════════════════════
#  Main — simple, proven capture loop
# ═══════════════════════════════════════════════════════════
def main():
    global current_frame, frame_count, fps_value
    ip = get_local_ip()

    print()
    print("=" * 58)
    print("  USB CAR DVR — Network Camera Bridge")
    print("=" * 58)

    # Connect with retry
    be = usb.backend.libusb1.get_backend()
    dev = None
    for attempt in range(30):
        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
        if dev:
            break
        sys.stdout.write("\r  Waiting for camera... (attempt {}/30)  ".format(attempt + 1))
        sys.stdout.flush()
        time.sleep(2)
    if not dev:
        print("\n  Camera NOT FOUND! Ensure WinUSB driver (Zadig).")
        print("  Camera: CAR_DVR / USB-MSDC DISK A")
        return

    def configure_device(device):
        """Detaches Linux kernel drivers (usb-storage) and sets USB config."""
        try:
            # For Linux: detach kernel driver if active
            for cfg in device:
                for intf in cfg:
                    if device.is_kernel_driver_active(intf.bInterfaceNumber):
                        try:
                            device.detach_kernel_driver(intf.bInterfaceNumber)
                        except usb.core.USBError as e:
                            print("  [Warning] Could not detach kernel driver: {}".format(e))
        except NotImplementedError:
            pass # is_kernel_driver_active is not implemented on Windows
        except Exception:
            pass
            
        try:
            device.set_configuration()
        except:
            pass

    configure_device(dev)
    clear_halt(dev)

    # INQUIRY
    try:
        cdb = bytes([0x12, 0, 0, 0, 0x24, 0])
        dev.write(EP_OUT, cbw(36, cdb), timeout=TIMEOUT)
        r = bytes(dev.read(EP_IN, 36, timeout=TIMEOUT))
        try: dev.read(EP_IN, 13, timeout=TIMEOUT)
        except: pass
        vendor = r[8:16].decode('ascii', errors='replace').strip()
        product = r[16:32].decode('ascii', errors='replace').strip()
        print("  Camera: {} / {}".format(vendor, product))
    except Exception as e:
        print("  Camera found but INQUIRY failed: {}".format(e))
        print("  Unplug camera for 5 seconds, replug, then restart.")
        return

    # Init sequence — GetStatus MUST come first to wake WCM handler
    import datetime
    try:
        # Step 1: GetStatus (wakes up the WCM protocol handler)
        print("  GetStatus...")
        wcm_send(dev, 9)
        time.sleep(0.3)
        d = scsi_read(dev, RESP_LBA, 1)
        print("  Status: {}".format(d[:8].hex()))

        # Step 2: SetDateTime
        now = datetime.datetime.now()
        dt = bytes([(now.year - 2000) & 0xFF, now.month, now.day,
                    now.hour, now.minute, now.second])
        wcm_send(dev, 19, data=dt)
        time.sleep(0.3)
        print("  DateTime: {}".format(now.strftime('%Y/%m/%d %H:%M:%S')))

        # Step 3: StartRecord
        wcm_send(dev, 1)
        print("  StartRecord: sent")
    except Exception as e:
        print("  Init failed: {}".format(e))
        print("  Unplug camera for 5 seconds, replug, then restart.")
        return

    # Start HTTP server FIRST (serves current_frame, initially None = 503)
    httpd = HTTPServer(('0.0.0.0', HTTP_PORT), CamHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # Start ONVIF
    threading.Thread(target=onvif_discovery_thread, daemon=True).start()
    threading.Thread(target=onvif_service_thread, daemon=True).start()

    # Open the Web UI automatically
    webbrowser.open('http://localhost:9090/')

    # OpenCV setup — opt-in with --show flag
    use_cv2 = '--show' in sys.argv
    cv2 = None
    np = None
    if use_cv2:
        try:
            import cv2 as _cv2
            import numpy as _np
            cv2 = _cv2
            np = _np
            print("  OpenCV: ENABLED (live window)")
        except ImportError:
            print("  OpenCV: not installed")
            use_cv2 = False
    else:
        print("  Mode: network only (use --show for OpenCV window)")

    print()
    print("  +-----------------------------------------------+")
    print("  |  LIVE -- 1280x720 @ ~20 FPS                   |")
    print("  |                                               |")
    print("  |  Web UI:  http://{}:{}/".format(ip, HTTP_PORT).ljust(50) + "|")
    print("  |  Stream:  http://{}:{}/stream".format(ip, HTTP_PORT).ljust(50) + "|")
    print("  |  Snap:    http://{}:{}/snapshot".format(ip, HTTP_PORT).ljust(50) + "|")
    print("  |  ONVIF:   auto-discovered (port {})".format(ONVIF_PORT).ljust(48) + "|")
    print("  |                                               |")
    print("  |  Press Q in OpenCV window or Ctrl+C to stop   |")
    print("  +-----------------------------------------------+")
    print()

    # === MAIN CAPTURE LOOP ===
    fps_start = time.time()
    fps_count = 0
    cv2_failed = False
    empty_count = 0

    def start_camera(device):
        """Send the init sequence: GetStatus -> SetDateTime -> StartRecord"""
        import datetime
        try:
            wcm_send(device, 9)
            time.sleep(0.2)
            scsi_read(device, RESP_LBA, 1)  # consume status response
            now = datetime.datetime.now()
            dt = bytes([(now.year - 2000) & 0xFF, now.month, now.day,
                        now.hour, now.minute, now.second])
            wcm_send(device, 19, data=dt)
            time.sleep(0.2)
            wcm_send(device, 1)
            return True
        except:
            return False

    # Initial start — go immediately into capture
    print("  Starting camera...", end='', flush=True)
    start_camera(dev)
    print(" OK")

    try:
        while True:
            try:
                frame = capture_one_frame(dev)
                if frame and len(frame) > 1000:
                    with frame_lock:
                        current_frame = frame
                    frame_count += 1
                    fps_count += 1
                    empty_count = 0

                    # FPS
                    elapsed = time.time() - fps_start
                    if elapsed >= 1.0:
                        fps_value = fps_count / elapsed
                        fps_count = 0
                        fps_start = time.time()

                    # Status line
                    if frame_count <= 5 or frame_count % 50 == 0:
                        sys.stdout.write("\r  Frame {:5d}  |  {:.1f} FPS  |  {:5.1f} KB  ".format(
                            frame_count, fps_value, len(frame) / 1024))
                        sys.stdout.flush()
                        if frame_count <= 5:
                            sys.stdout.write("\n")

                    # OpenCV display (optional)
                    if use_cv2 and not cv2_failed:
                        try:
                            nparr = np.frombuffer(frame, np.uint8)
                            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img is not None:
                                cv2.putText(img, "{:.1f} FPS".format(fps_value),
                                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                            0.7, (0, 255, 0), 2)
                                cv2.imshow('USB DVR Network Camera', img)
                                key = cv2.waitKey(1) & 0xFF
                                if key == ord('q'):
                                    break
                        except Exception as e:
                            print("\n  OpenCV display failed: {} -- headless".format(e))
                            cv2_failed = True
                else:
                    empty_count += 1
                    if empty_count == 1 or empty_count % 100 == 0:
                        sys.stdout.write("\r  Waiting for frames... ({} empty reads)  ".format(empty_count))
                        sys.stdout.flush()
                    
                    # Re-init camera after 10s of dead stream
                    if empty_count >= 200:
                        sys.stdout.write("\n  Camera stalled (10s limit). Performing hardware reset... \n")
                        sys.stdout.flush()
                        try:
                            usb.util.dispose_resources(dev)
                            dev.reset()
                        except:
                            pass
                        time.sleep(1.5)
                        # Re-find device
                        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
                        if dev:
                            configure_device(dev)
                            start_camera(dev)
                            empty_count = 0
                        else:
                            sys.stdout.write("  Device not found. Retrying in 1s...\n")
                            time.sleep(1)
                    else:
                        time.sleep(0.05)

            except usb.core.USBError as e:
                if 'Pipe' in str(e) or 'Input/Output' in str(e):
                    try:
                        clear_halt(dev)
                    except:
                        pass
                    # If we pipe error repeatedly, count it as an empty read to trigger hardware reset
                    empty_count += 10
                    time.sleep(0.1)
                else:
                    print("\n  USB Error: {} -- reconnecting...".format(e))
                    time.sleep(3)
                    try:
                        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
                        if dev:
                            try: dev.set_configuration()
                            except: pass
                            clear_halt(dev)
                            start_camera(dev)
                            print("  Reconnected!")
                        else:
                            print("  Camera not found, will retry...")
                    except Exception as e2:
                        print("  Reconnect error: {}".format(e2))

    except KeyboardInterrupt:
        pass

    if use_cv2 and not cv2_failed:
        try: cv2.destroyAllWindows()
        except: pass

    print("\n\n  {} frames captured.".format(frame_count))

if __name__ == '__main__':
    main()
