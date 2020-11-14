# change log

## 2020-11-14
1. Made dropping root privileges a config option
2. Added configuration option for user to use when dropping root privileges
3. Added buttons to top level web page to reboot or power off the Pi.
Buttons will not be shown if the user running the daemon does not have privileges to run the commands (see source code for details)
4. Added URLs to reboot or power off the Pi.
URLs will not be available if the user running the daemon does not have privileges to run the commands (see source code for details)
5. Updated default.cfg
6. Updated README.md
7. Moved drop privileges code outside and before main loop.
8. More code tidying
9. Fixed bug with booleans when reading config file and a section is missing.

## 2020-10-04
1. Migrated from python2 to python 3. PITA especially the byte vs unicode strings.
2. Added support for multiple ping targets (see https://github.com/thagrol/fakewake/issues/3).
config file now accepts a comma seperated list of IP addresses or host names.
3. Added missing button press code for AUX1 and AUX2
4. Stopped cleanup code throwing an exception where a GPIO had not been setup.
5. New configuration parameter "pinger_enabled". Allows pinger to be disabled even when targets have been specified.
6. Additional debug code
7. Tidied code.
8. Updated README.md
9. Update default.cfg
