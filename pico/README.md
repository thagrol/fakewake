Initial and incomplete port to PicoW.

Currently only WoL packets are supported.
There is no web server, pinger, or thread management.

## Installation
1. Install micropython on your PicoW.
2. Copy main.py to the PicoW's micropython file system
3. Copy default-config.py to config.py
4. Edit config.py to match your configuration
5. Copy config.py to the PicoW's micropython file system

## Hardware Connection
1. Tap the PC PSU's 5v standby line to feed power to the PicoW (e.g. via its USB port)
2. Connect GPIO as per the PI version.
