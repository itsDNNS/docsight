#!/usr/bin/env python3
"""Debug script to test Vodafone Station login directly.

Usage:
    python3 debug_vodafone_login.py <url> <password>
    
Example:
    python3 debug_vodafone_login.py http://192.168.0.1 mypassword
"""

import sys
import logging
import os

# Add app to path
sys.path.insert(0, os.path.dirname(__file__))

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.drivers.vodafone import VodafoneStationDriver

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 debug_vodafone_login.py <url> <password>")
        print("Example: python3 debug_vodafone_login.py http://192.168.0.1 mypassword")
        sys.exit(1)
    
    url = sys.argv[1]
    password = sys.argv[2]
    username = sys.argv[3] if len(sys.argv) > 3 else "admin"
    
    print(f"\n{'='*60}")
    print(f"Testing Vodafone Station Login")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    print(f"{'='*60}\n")
    
    driver = VodafoneStationDriver()
    
    print("Attempting login...")
    session = driver.login(url, username, password, timeout=10)
    
    if session:
        print(f"\n✅ LOGIN SUCCESS!")
        print(f"Session type: {type(session)}")
        print(f"Session headers: {dict(session.headers)}")
        
        print("\nTesting device info fetch...")
        try:
            device_info = driver.get_device_info(session, url)
            print(f"✅ Device info: {device_info}")
        except Exception as e:
            print(f"❌ Device info failed: {e}")
        
        print("\nTesting DOCSIS data fetch...")
        try:
            docsis_data = driver.get_docsis_data(session, url)
            print(f"✅ DOCSIS data structure:")
            print(f"   - DS DOCSIS 3.0 channels: {len(docsis_data.get('channelDs', {}).get('docsis30', []))}")
            print(f"   - DS DOCSIS 3.1 channels: {len(docsis_data.get('channelDs', {}).get('docsis31', []))}")
            print(f"   - US DOCSIS 3.0 channels: {len(docsis_data.get('channelUs', {}).get('docsis30', []))}")
            print(f"   - US DOCSIS 3.1 channels: {len(docsis_data.get('channelUs', {}).get('docsis31', []))}")
        except Exception as e:
            print(f"❌ DOCSIS data failed: {e}")
    else:
        print(f"\n❌ LOGIN FAILED!")
        print("Check the debug logs above for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
