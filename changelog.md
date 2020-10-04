# change log

##2020-10-04

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
