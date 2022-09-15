Initial and incomplete port to PicoW.

Web server and wake on lan now implimented.

Still no pinger, and currently no log file.


## Installation
1. Install micropython on your PicoW.
2. Copy main.py to the PicoW's micropython file system
3. Copy default-config.py to config.py
4. Edit config.py to match your configuration
5. Copy config.py to the PicoW's micropython file system

## Hardware Connection
1. Tap the PC PSU's 5v standby line to feed power to the PicoW (e.g. via its USB port)
2. Connect GPIO as per the PI version.

## Known Issues
1. As of rp2-pico-w-20220914-unstable-v1.19.1-409-g0e8c2204d.uf2 setting hostname does not appear to be supported.
It will be necessary to check your router or use a network scanner to find the hostname and IP address.
2. If the WiFi connection is lost it is likely the PicoW will need to be manually reset.
3. Neither debug output nor the /config web page redact your WiFi password.
