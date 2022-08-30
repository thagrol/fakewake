## imports
import machine
import struct

import io
import network
import os
import rp2
import select
import struct
import sys
import time

onboardled = machine.Pin("LED", machine.Pin.OUT)

def blinkled(timer):
    global onboardled
    onboardled.toggle()

def errorled():
    t = machine.Timer()
    t.init(freq=2.5, mode=machine.Timer.PERIODIC, callback=blinkled)

try:
    import socket
except ImportError:
    print('Unable to import socket module. Is this a Pico W and if not has it been compiled in to micropython?')
    errorled()
    sys.exit(1)

## read config
try:
    import config
except ImportError:
    errorled()
    raise RuntimeError('Configuration file not found.')
if config.wol['enabled'] == False and config.webserver['enabled'] == False:
    errorled()
    raise RuntimeError('Nothing to do. WoL and Web are disabled')

## constants
WLANSTATUS = {0:'(link down)',
             1:'(unable to join)',
             2:'(no IP address)',
             3:'(link up)',
             -1:'link fail)',
             -2:'(no network - check SSID)',
             -3:'(Bad auth - check password)' }


## flags
actionspaused = False


## function definitions
def debugprint(s):
    if config.debug:
        s = str(s)
        try:
            print('%s:%s:%s' % (time.time(),__file__,s))
        except Exception as e:
            print('%s::%s' % (time.time(),s))

def wol_listener():
    # wake on lan listerner(s)
    # this is about as basic as it can get
    # not fully compliant with WOL spec as packets will only been seen when sent as UDP to a know port
    # (usually 7 and/or 9)
    # this will not wake a PC from sleep if the PSU remains fully on
    # true WOL requires examining every ethernet frame received by the network interface
      
    # create and start listeners
    debugprint('Creating listeners')
    listeners = []
    for port in config.wol['ports']:
        try:
            debugprint('Trying on port %s' % port)
            listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listener.setblocking(0)
            listener.bind(('', port))
            listeners.append(listener)
            debugprint('Success ')
        except Exception as e:
            logging.error('Failed to start WOL listener on port %s %s', port, str(e))
    if len(listeners) ==  0:
        logging.error('Failed to start any WOL listeners. Exiting thread and disabling WOL listener.')
        WOL_ENABLED = False
        return

    debugprint('Started %s listener(s) on ports %s' % (len(listeners), config.wol['ports']))

#    while stop_threads == False:
    while True:
        # now we can actually do some listening
        r, w, e = select.select(listeners, [], [], 0)
        for s in r:
            inc = b''
            inc, sender = s.recvfrom(1024)
            debugprint('data received from %s' % sender[0])
            debugprint('\t%s' % inc)
            # validate host
            if valid_host(sender[0]) == False:
                debugprint('invalid sender. Ignoring magic packet.')
                continue
            if actionspaused:
                print('Ignoring magic packet. Too soon after last action')
                break
            for k in magic_packets:
                debugprint('Matching against: %s' % k)
                if (magic_packets[k] is not None
                    and magic_packets[k] in inc):
                    debugprint('Matched %s' % k)
                    try:
                        # it's a magic packet we want to handle
                        if k in ('wake', 'shutdown', 'forceoff'):
                            debugprint("Setting button to 'power'")
                            target_button = 'power'
                        elif k == 'reset':
                            target_button = 'reset'
                        elif k == 'aux1':
                            target_button = 'aux1'
                        elif k == 'aux2':
                            target_button = 'aux'
                        else:
                            # reserved for future use
                            print('WARNING: unknown button %s' % k)
                    except NameError:
                        debugprint('No pin configured for function.')
                        target_button = None
                    if k == 'forceoff':
                        target_duration = config.timings['long']
                    else:
                        target_duration = config.timings['short']
                    debugprint('Press duration set to %s' % target_duration)
                    go_nogo = False
                    if 'psu_sense' in inputs:
                        if (k == 'wake'
                            and psustate() == False):
                            go_nogo = True
                        if (k in ('shutdown', 'forceoff', 'reset')
                            and psustate() == True):
                            go_nogo = True
                    if k in ('aux1', 'aux2'):
                        go_nogo = True
                    debugprint('calculated go/nogo state: %s' % go_nogo)
                    if config.debug:
                        go_nogo = True

                    if go_nogo:
                        # press button here
                        pushbutton(target_button, target_duration)
                    else:
                        debugprint('%s packet ignored due to current PSU state' % k)
                    break
                else:
                    debugprint('Recieved data does not match %s packet' % k)
        time.sleep(0.1)

    for listener in listeners:
        listener.close()
    debugprint('exiting')

def valid_host(ipaddr):
    # validate ipaddr against HOST_ALLOW and HOSTS_DENY
    #
    # usual unix/linux rules:
    #    valid if ipaddr in HOSTS_ALLOW
    #    otherwise invalid if in HOSTS_DENY
    #    otherwise valid
    #
    # empty lists disable access control
    # a single entry of '*' in HOSTS_DENY blocks all hosts
    # not listed in HOSTS_ALLOW

    debugprint('HOSTS_ALLOW %s' % config.hosts['allow'])
    debugprint('HOSTS_DENY %s' % config.hosts['deny'])
    # make sure we have a string
    ipaddr = str(ipaddr)
    debugprint('ipaddr to check %s' % ipaddr)

    if ipaddr in config.hosts['allow']:
        # always allowed
        return True

    if '*' in config.hosts['deny']:
        # all denied
        return False

    if ipaddr in config.hosts['deny']:
        # allow all except denied
        return False

    # otherwise
    # default action
    return True

def clearpause(dummy):
    global actionspaused
    actionspaused = False
    debugprint('Clearing paused flag')

def pushbutton(button, duration):
    global actionspaused
    if button is None or button.strip() == '':
        return
    if actionspaused:
        print('Unable to comply - waiting for minimum time between actions')
        return
    try:
        outputs[button].on()
        t = machine.Timer()
        t.init(mode=machine.Timer.ONE_SHOT, period=int(duration * 1000), callback=lambda cb:outputs[button].off())
        t2 = machine.Timer()
        t2.init(mode=machine.Timer.ONE_SHOT, period=int(config.timings['min_interval'] * 1000), callback=clearpause)
        actionspaused = True
    except Exception as e:
        print('ERROR:Exception while pressing button %s: %s' % (button, e),file=sys.stderr)

def psustate():
    result = bool(inputs['psu_sense'].value())
    debugprint('Actual psu_sense pin state: %s' % result)
    if config.pins['psu_sense_active_low'] == True:
        result = not(result)
    debugprint('Returning psu state of %s' % result)
    return result


## create magic packets
debugprint('Creating reference magic packets')
magic_packets = {}
if config.wol['enabled'] and len(config.wol['ports']) > 0:
    for k, v in config.wol.items():
        if k == 'enabled' or k == 'ports':
            continue
        debugprint('%s = %s' % (k, v))
        if v is None or v.strip() == '':
            debugprint('No MAC address for ' + k)
            continue
        try:
            splitmac = v.split(':')
            debugprint('Split MAC address for %s = %s' % (k, splitmac))
            magic_packets[k] = b'\xff' * 6 + \
                              struct.pack(b'!BBBBBB',
                                          int(splitmac[0], 16),
                                          int(splitmac[1], 16),
                                          int(splitmac[2], 16),
                                          int(splitmac[3], 16),
                                          int(splitmac[4], 16),
                                          int(splitmac[5], 16)) * 16
        except Exception as e:
            print('WARNING: unable to create magic packet for %s:%s.' % (k, v))
            print(e)
    debugprint('Created magicpackets: %s' % magic_packets)

## create pin objects
debugprint('Creating output pin objects')
outputs = {}
for k, v in config.pins.items():
    if k.startswith('psu_sense'):
        # input pin fucntion ot config
        continue
    if v is not None:
        try:
            outputs[k] = machine.Pin(v, machine.Pin.OUT)
        except Exception as e:
            debugprint('Failed to create object for %s due to %s' % (k,e))
debugprint(outputs)
if len(outputs) == 0:
    errorled()
    raise RuntimeError('ERROR: no output objects/pins. Exiting')
# there is only one input pin currently.
inputs = {}
if config.pins['psu_sense'] is not None:
    desiredpull = machine.Pin.PULL_DOWN
    try:
        if config.pins['psu_sense_active_low']:
            desiredpull = machine.Pin.PULL_UP
    except KeyError:
        pass
    try:
        inputs['psu_sense'] = machine.Pin(config.pins['psu_sense'],
                                          desiredpull)
    except Exception as e:
        print('ERROR: Failed to create object for psu_sense due to %s'
              % e, file=sys.stderr)
        config.pins['psu_sense'] = None

## connect to WiFi
# set country
if config.wlan['country'] is not None:
    debugprnit('setting country to %s' % config.wlan['country'])
    try:
        rp2.country(config.wlan['country'])
    except Exception as e:
        print('WARNING: failed to set country code. Using default instead.')
        debugprint(str(e))
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
# disable power management
wlan.config(pm = 0xa11140)
# start connection
debugprint('attempting to connect to SSID: %s with password: %s' % (config.wlan['ssid'], config.wlan['password']))
wlan.connect(config.wlan['ssid'], config.wlan['password'])
# wait for connection og fail
maxwait = config.wlan['maxwait']
while maxwait > 0:
    if wlan.status() < 0 or wlan.status() >= 3:
        break
    maxwait -= 1
    print('waiting for connection...')
    time.sleep(1)
# report status and handle failure
if wlan.status() != 3:
    errorled()
    raise RuntimeError('Network connection failed with status %s %s' % (wlan.status(), WOLSTATUS[wlan.status()]))
print('Connected. My IP is: %s' % wlan.ifconfig()[0])
debugprint(wlan.ifconfig())
## all good so far so tell the world
#onboardled.value(1)

if config.wol['enabled']:
    if config.pins['psu_sense'] is None:
        print('WARNING:No configured psu_sense pin. Magic packets for power control will be ignored')
    if len(magic_packets) > 0 or\
       ('aux1' in magicpackets or 'aux2' in magicpackets):
        debugprint('Staring WoL listeners')
        wol_listener()
    else:
        print('WARNING: WoL listeners not started as there is nothing to listen for')
