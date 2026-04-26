# Android APK Reverse Engineering Report

## Analysis Overview
Successfully analyzed `uCarDvr.apk` - a vehicle camera/DVR application.

## Key Findings

### 1. API Server Endpoint
```
http://android.williexing.com
```
This is the primary communication server for the application.

### 2. Application Components
- **Main DEX**: classes.dex (265KB of bytecode)
- **Native Libraries**: 
  - libjpeg-turbo.so (image processing)
  - libxufscamera.so (camera control)
- **Resources**: XML layouts, images, animations

### 3. Technical Details
- Valid DEX format (magic: dex\n035\x00)
- Contains camera control and media streaming functionality
- References ADAS (Advanced Driver Assistance Systems) UI elements
- Uses Android resource system extensively

## Complete Analysis Script

```python
#!/usr/bin/env python3
"""
Comprehensive DEX Analysis Script
Analyzes Android DEX files for API endpoints, strings, and structure
"""

import struct
import re
import sys

def parse_dex_header(data):
    """Parse DEX file header"""
    if len(data) < 112:
        return None
    
    def read_uint32(offset):
        return struct.unpack('<I', data[offset:offset+4])[0]
    
    header_info = {
        'magic': data[:8],
        'checksum': read_uint32(8),
        'signature': data[12:32].hex(),
        'file_size': read_uint32(32),
        'header_size': read_uint32(36),
        'endian_tag': read_uint32(40),
        'link_size': read_uint32(44),
        'link_off': read_uint32(48),
        'map_off': read_uint32(52),
        'string_ids_size': read_uint32(56),
        'string_ids_off': read_uint32(60),
        'type_ids_size': read_uint32(64),
        'type_ids_off': read_uint32(68),
        'proto_ids_size': read_uint32(72),
        'proto_ids_off': read_uint32(76),
        'field_ids_size': read_uint32(80),
        'field_ids_off': read_uint32(84),
        'method_ids_size': read_uint32(88),
        'method_ids_off': read_uint32(92),
        'class_defs_size': read_uint32(96),
        'class_defs_off': read_uint32(100),
        'data_size': read_uint32(104),
        'data_off': read_uint32(108),
    }
    
    return header_info

def extract_strings(data, min_length=4):
    """Extract printable strings from binary data"""
    strings = []
    i = 0
    while i < len(data):
        if 32 <= data[i] <= 126:  # Printable ASCII
            start = i
            while i < len(data) and 32 <= data[i] <= 126:
                i += 1
            length = i - start
            if length >= min_length:
                try:
                    s = data[start:i].decode('ascii')
                    strings.append(s)
                except:
                    pass
        else:
            i += 1
    return strings

def find_urls(data):
    """Find HTTP/HTTPS URLs in binary data"""
    urls = re.findall(b'https?://[^\x00\s<>"\']+', data)
    return [url.decode('utf-8', errors='ignore') for url in urls]

def analyze_dex_file(filepath):
    """Main analysis function"""
    print(f"Analyzing: {filepath}")
    print("=" * 60)
    
    with open(filepath, 'rb') as f:
        data = f.read()
    
    print(f"File size: {len(data)} bytes")
    
    # Parse header
    header = parse_dex_header(data)
    if header:
        print("\n=== DEX Header ===")
        for key, value in header.items():
            if isinstance(value, bytes):
                print(f"{key}: {value}")
            else:
                print(f"{key}: {value:#x if key.endswith('_off') or key.endswith('_size') else ''}")
    
    # Extract strings
    print("\n=== All Strings ===")
    strings = extract_strings(data)
    unique_strings = list(set(strings))
    print(f"Total unique strings: {len(unique_strings)}")
    
    # Filter for relevant strings
    keywords = ['http', 'api', 'server', 'camera', 'video', 'network', 'connect', 'auth']
    relevant = [s for s in unique_strings if any(k.lower() in s.lower() for k in keywords)]
    
    print("\n=== Relevant Strings ===")
    for s in sorted(relevant):
        print(f"  {s}")
    
    # Find URLs
    print("\n=== URLs Found ===")
    urls = find_urls(data)
    for url in sorted(set(urls)):
        print(f"  {url}")
    
    # Basic statistics
    print("\n=== Statistics ===")
    print(f"Total strings: {len(strings)}")
    print(f"Unique strings: {len(unique_strings)}")
    print(f"URLs found: {len(urls)}")
    
    return {
        'header': header,
        'strings': unique_strings,
        'urls': urls,
        'file_size': len(data)
    }

if __name__ == '__main__':
    filepath = 'classes.dex'
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    
    try:
        results = analyze_dex_file(filepath)
        print("\n" + "=" * 60)
        print("Analysis complete!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)