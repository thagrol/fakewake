"""micropython does not support the configparser or argparse modules so..."""

## enable debug
debug = False

## display name of PC being controlled
pc = 'My PC'

## wlan
wlan = { 'ssid':'',
         'password':'',
         # country should only need to be set if the default doesn't work
         # or you cannot acces some channels that you need to.
         'country':None,
         #maximum time to wait for a wifi connection. Seconds.
         'maxwait': 30,
         # this is here because it's a parameter of WLAN.config()
         # but is doesn't appear to be currently supported in client mode
         'hostname':'fakewake' }

## pins
##   set to None to disable feature
##   but note that disabling power_pin defeats the object of this tool
pins = { 'power':"LED",
         'reset':None,
         # if psu_sense is not enabled wol support will be disabled as it could cause an unexpected shutdown or reset
         'psu_sense':None,
         # set to True if your PSU sense hardware pulls the pin low when the PSU
         #   is on.
         'psu_sense_active_low':False,
         # the M74HC4066B1R contains 4 switches.
         # these may be used in the same way as 'power' and 'reset'
         # by setting non-zero values
         # only 'short' button press durations are currently supported
         # on these
         'aux1':None,
         'aux2':None }

## timings
## button press durations (seconds)
## long must be greater than 4.0 for most PCs
timings = { 'short':0.25,
            'long':5.0,
            # minimum interval between actions (seconds)
            # must be greater than LONG_PRESS
            # and should be greater than the expected boot/shutdown time
            # of the target PC
            # must also be less than any configured screen power off/sleep
            # time on the target PC as some OS use the power button as a
            # wake trigger from this state(PC on but screens off)
            'min_interval':180.0 }

## webserver
webserver = { 'enabled':False,
              'port':80,
              # time between automatic page reloads in seconds
              # should be longer than "long" above
              'reload_delay':15 }

## Wake on LAN
wol = { 'enabled':True,
        ''
        # list of UDP ports to listen on for wol packets
        'ports':[7, 9],

        # MAC addresses must be written '00:11:22:33:44:55'
        # all four addresses must be different
        # it's best to use mac addresses in the "locally administered"
        # range i.e. 
        #            x2:xx:xx:xx:xx:xx
        #            x6:xx:xx:xx:xx:xx
        #            xA:xx:xx:xx:xx:xx
        #            xE:xx:xx:xx:xx:xx
        # where x is any hexadecimal digit
        # to avoid conflicts none of these should exist on your LAN.
        'wake':'EE:11:22:33:44:00',

        # magic packets sent to these addresses will perform the
        # relevant action
        'shutdown':None,
        'reset':None,
        'forceoff':None,

        # aux channels will fire regardless of PSU state when a magic
        # packet is received
        'aux1':None,
        'aux2':None }

## ping target
pinger = { 'enabled':False,
           'target':None,
           'interval':1.0 } # in seconds

## security
## host ip based security measure
## list of ipv4 addresses
##
## functions in a similar manner to the system files
## hosts.allow and hosts.deny:
##   Access will be granted when a client's ip address matches an entry in hosts_allow.
##   Otherwise, access will be denied when a client's ip address matches an entry in hosts_allow.
##   Otherwise, access will be granted.
##
## default is to allow all ip addresses and deny none
## use * for hosts_deny to block all addresses except those in hosts_allow
## example 1: allow access from any ip address
##    hosts = { 'allow':[],
##              'deny':[] }
### example 2: block all clients except those on localhost
##    hosts = { 'allow':['127.0.0.1'],
##              'deny':['*'] }
hosts = { 'allow':[],
          'deny':[] }

if debug:
    for name in dir():
        if not name.startswith('__'):
            print('%s:%s = %s' % (__file__,name, eval(name)))

    
