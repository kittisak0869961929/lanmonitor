# LAN Monitor
Windows command-line LAN device listing with monitoring of connection changes and optional pop-up window to alert (dis)connection of specified devices.

A list of LAN devices is provided, with the ability to save custom device names.  

It automatically generates a device name from the manufacturer name retrieved from an API call to a third-party MAC address manufacturer lookup service. (https://macvendors.com/api)

Devices on the LAN have their names stored in SQLite file named clients.db in program folder.
