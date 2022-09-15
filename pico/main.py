## imports

#import io
import machine
import network
import ntptime
import os
import rp2
import select
import struct
import sys
import time


onboardled = machine.Pin("LED", machine.Pin.OUT)


## these two need to be defined here.
def blinkled(timer):
    global onboardled
    onboardled.toggle()

def errorled():
    t = machine.Timer()
    t.init(freq=2.5, mode=machine.Timer.PERIODIC, callback=blinkled)


try:
    import socket
except ImportError:
    errorled()
    raise

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
HTML = {'base_header':'HTTP/1.0 ',
        'ok_header':'200 OK\n\n',
        'html_header':'<!DOCTYPE HTML>\n<html><head><title>fakewake</title>\n',
        'clacks_header':'<meta http-equiv="X-Clacks-Overhead" content="GNU Terry Pratchett" />\n',
        'refresh_header':'<meta http-equiv="refresh" content="%s;/">' % config.webserver['reload_delay'],
        'end_header':'</head><body>',
        'my_header':'<hr><h2><h1>%s</h2><form action="/log" method="get"><input type="submit" value="View log"></form><br><form action="/config" method="get"><input type="submit" value="View config"></form><br>' % config.wlan['hostname'],
        'my_controls':'<form action="/rebootme" method="get"><input type="submit" value="Reset"></form>'
        }
HTML['error403'] = HTML['base_header'] + HTML['ok_header'] + HTML['html_header']\
                   + HTML['clacks_header'] + HTML['end_header'] + '<h2>403 Forbidden</h2></body></html>'
HTML['error404'] = HTML['base_header'] + HTML['ok_header'] + HTML['html_header']\
                   + HTML['clacks_header'] + HTML['end_header']\
                   + '<h2>404: This space unintentionally left blank</h2></body></html>'
HTML['error405'] = HTML['base_header'] + '405 Method Not Allowed\n'\
                   + HTML['html_header'] + HTML['clacks_header']\
                   + HTML['end_header'] + '<h2>405 Method Not Allowed</h2></body></html>'


## globals
sockets = []
wolsockets = []
websockets = []


## flags
actionspaused = False


## function definitions
def debugprint(s):
    if config.debug:
#        s = str(s)
        try:
            print('%s:%s:%s' % (time.time(),__file__,s))
        except Exception as e:
            print('%s::%s' % (time.time(),s))

def listen(sockets):
    debugprint(sockets)
    while True:
        r, w, e = select.select(sockets, [], [], 0)
        if len(r) > 0\
           or len(w) >0\
           or len(e) >0:
            debugprint('%s %s %s' %(r,w,e))
        for s in r:
            if s in wolsockets:
                dowol(s)
            if s in websockets:
                debugprint('web socket has data')
                doweb(s)
        # Do Not remove this sleep or timers will not fire.
        time.sleep(0.1)

def dowol(s):
    debugprint('doing WOL stuff here')
    packet, sender = s.recvfrom(1024)
    if actionspaused:
        print('Ignoring magic packet. Too soon after last action')
        return
    if valid_host(sender[0]) == False:
        debugprint('Invalid sender. Ignoring data.')
        return
    for k in magic_packets:
        debugprint('Matching against: %s' % k)
        if (magic_packets[k] is not None
            and magic_packets[k] in packet):
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

def doweb(server_socket):
    debugprint('web request received')
    client_socket, client_address = server_socket.accept()
    # couldn't get this code to work without switching back to a
    # blocking socket. Constant OSError 11 when non-blocking
    client_socket.setblocking(1)
    debugprint('\tfrom ' + client_address[0])
    # send error 403 if client is invalid
    if valid_host(client_address[0]) == False:
        debugprint('Invalid source. Sending 403')
        client_socket.sendall(HTML['error403'])
        client_socket.shutdown(socket.SHUT_RDWR)
        client_socket.close
        return
    debugprint('\tReading Request')
    # read request
    request = client_socket.recv(4096)
    try:
        request = request.decode()
    except UnicodeError:
        print('Warning: unable to decode request to unicode. Trying str() instead.')
        request = str(request)
    # parse request
    for line in request.splitlines():
        prefix = line.split(' ',1)[0]
        if prefix in ('POST', 'HEAD', 'PUT', 'DELETE',
                        'OPTIONS', 'CONNECT'):
            debugprint('Sending Error 405')
            client_socket.sendall(HTML['error405'].encode())
        elif prefix != 'GET':
            # don't know and don't care what this is
            pass
        else:
            # must be a GET request
            debugprint('\tMust be a GET request')
            method, url, trailer = line.split()
            # need this due to form/button hack in html code
            url = url.split('?')[0]
            if url == '':
                url = '/'
            # force url to lowercase
            url = url.lower()
            debugprint('\trequested url: %s' % url)
            if url not in ('/', '/power', '/forcepower','/reset','/config', '/log','/rebootme'):
                client_socket.sendall(HTML['error404'].encode())
            elif url == '/log':
                 # show log file
                 client_socket.sendall(HTML['error404'].encode())
            elif url == '/config':
                # show config
                try:
                    with open('config.py', 'r') as c:
                        reply = HTML['base_header'] + HTML['ok_header']\
                                + c.read()
                except Exception:
                    reply = HTML['error404;']
                client_socket.sendall(reply.encode())
            elif url == '/':
                # assemble page
                if actionspaused:
                    button_state = 'disabled'
                else:
                    button_state = ''
                reply = HTML['base_header'] + HTML['ok_header']\
                        + HTML['html_header'] + HTML['clacks_header']\
                        + HTML['refresh_header'] + HTML['end_header']\
                        + '<h1>' + str(config.pc) +'</h1>'
                reply += '<b>PSU State:</b> '
                if 'psu_sense' in inputs:
                    if psustate():
                        reply += 'On'
                    else:
                        reply += 'Off/Standby'
                else:
                    reply += 'Unknown'
#                reply += '<br><b>Pingable:</b> %s' % PINGABLE
                if 'power' in outputs:
                    reply += '<br><form action="/power" method="get">'
                    reply += '<input type="submit" value="Power On/Off" %s></form><br>' % button_state
                    reply += '<form action="/forcepower" method="get">'
                    reply += '<input type="submit" value="Force Power Off" %s></form><br>' % button_state
                if 'reset' in outputs:
                    reply += '<form action="/reset" method="get">'
                    reply += '<input type="submit" value="Reset" %s></form><br>' % button_state
                if 'aux1' in outputs:
                    reply += '<form action="/aux1" method="get">'
                    reply += '<input type="submit" value="Aux 1" %s></form><br>' % button_state
                if 'aux2' in outputs:
                    reply += '<form action="/aux2" method="get">'
                    reply += '<input type="submit" value="Aux 2" %s></form><br>' % button_state
                reply += HTML['my_header']
                reply += HTML['my_controls']
                reply += '</body></html>'
                # send reply
                client_socket.sendall(reply.encode())
            else:
                # prepare reply
                # this is the same for all actions
                reply = HTML['base_header'] + HTML['ok_header']\
                        + HTML['html_header'] + HTML['clacks_header']\
                        + HTML['refresh_header']
                reply += 'Working. Please wait...'
                reply += '<center><form action="/" method="get">'
                reply += '<input type="submit" value="Continue">'
                reply += '</form></center></body></html>'
                # do action
                if url == '/power':
                    if 'power' in outputs:
                        pushbutton('power', config.timings['short'])
                        client_socket.sendall(reply.encode())
                    else:
                        client_sendall(HTML['error404'].encode())
                if url == '/forcepower':
                    if 'power' in outputs:
                        pushbutton('power', config.timings['long'])
                        client_socket.sendall(reply.encode())
                    else:
                        client_sendall(HTML['error404'].encode())
                if url == '/reset':
                    if 'reset' in outputs:
                        pushbutton('reset', config.timings['short'])
                        client_socket.sendall(reply.encode())
                    else:
                        client_sendall(HTML['error404'].encode())
                if url.startswith('/aux'):
                    if url[1:] in outputs:
                        pushbutton(url[1:], config.timings['short'])
                        client_socket.sendall(reply.encode())
                    else:
                        client_sendall(HTML['error404'].encode())
            if url == '/rebootme':
                client_socket.sendall(reply.encode())
                machine.reset()
    client_socket.close()

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

    # make sure we have a string
    ipaddr = str(ipaddr)
    debugprint('ipaddr to check %s' % ipaddr)
    
    debugprint('HOSTS_ALLOW %s' % config.hosts['allow'])
    debugprint('HOSTS_DENY %s' % config.hosts['deny'])

    if ipaddr in config.hosts['allow']:
        # always allowed
        valid = True
    elif '*' in config.hosts['deny'] or ipaddr in config.hosts['deny']:
            # all denied
            valid = False
    else:
        # default action
        valid = True
        
    debugprint('valid: ' + str(valid))
    return valid

def clearpause(dummy):
    global actionspaused
    actionspaused = False
    debugprint('Clearing paused flag')

def pushbutton(button, duration):
    global actionspaused
    debugprint('entered pushbutton(%s, %s)' % (button, duration))
    if button is None or button.strip() == '':
        return
    if actionspaused:
        print('Unable to comply - waiting for minimum time between actions')
        return
    try:
        debugprint('setting pin output state')
        outputs[button].on()
        t = machine.Timer()
        debugprint('starting pin rest timer')
        t.init(mode=machine.Timer.ONE_SHOT, period=int(duration * 1000), callback=lambda cb:outputs[button].off())
        t2 = machine.Timer()
        debugprint('starting pause actions timer')
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


try:
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
            # input pin - ignore for now
            continue
        if v is not None:
            try:
                outputs[k] = machine.Pin(v, machine.Pin.OUT)
            except Exception as e:
                debugprint('Failed to create object for %s due to %s' % (k,e))
    debugprint(outputs)
    if len(outputs) == 0:
        #errorled()
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
        debugprint('setting country to %s' % config.wlan['country'])
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
        #errorled()
        raise RuntimeError('Network connection failed with status %s %s' % (wlan.status(), WOLSTATUS[wlan.status()]))
    print('Connected. My IP is: %s' % wlan.ifconfig()[0])
    debugprint(wlan.ifconfig())
    debugprint('wlan config:')
    for k in ['mac', 'ssid', 'channel', 'hidden', 'security', 'key',
              'hostname', 'reconnects', 'txpower']:
        try:
            if k == 'mac':
                debugprint('\t%s:\t%s' % (k, wlan.config(k).hex()))
            else:
                debugprint('\t%s:\t%s' % (k, wlan.config(k)))
        except ValueError:
            debugprint('\t%s:\tnot supported' % k)

    # set RTC. UTC only for now.
    try:
        ntptime.settime()
    except Exception as e:
        print('WARNING: unable to set time due to %s' % e)

    # all good so far so tell the world
    onboardled.value(1)
    if config.debug:
        onboardled.value(0)

    portlist = []

    if config.wol['enabled']:
        if config.pins['psu_sense'] is None:
            print('WARNING: No configured psu_sense pin. Magic packets for power control will be ignored')
            if len(magic_packets) > 0:
                portlist += config.wol['ports']
            else:
                print('WARNING: WoL listeners will not be started as there is nothing to listen for')

    if config.webserver['enabled']:
        if config.webserver['port'] in config.wol['ports']:
            print('WARNING: webserver port %s already in use for WoL. Webserver will not be available')
        else:
            portlist.append(config.webserver['port'])

    if len(portlist) == 0:
        raise RuntimError('No ports to open')

    debugprint('Opening sockets')
    for port in portlist:
        addr = socket.getaddrinfo('0.0.0.0', port)[0][-1]
        try:
            debugprint('\tTrying on port %s' % port)
            if port in config.wol['ports']:
                debugprint('\t\twol port')
                listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                listener.setblocking(0)
                listener.bind(addr)
                wolsockets.append(listener)
                debugprint('\t\tsuccess')
            elif port == config.webserver['port']:
                debugprint('\t\tweb port')
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.setblocking(0)
                listener.bind(addr)
                listener.listen(5)
                websockets.append(listener)
                debugprint('\t\tsuccess')
            else:
                print('Warning. You should never see this.')
                continue
        except Exception as e:
            print('WARNING:Failed to open socket on port %s %s' % (port, e))
            continue
            raise
        sockets.append(listener)

    if len(sockets) == 0:
        raise RuntimeError('Failed to open any ports.')
    debugprint('wol sockets %s' % wolsockets)
    debugprint('web sockets %s' % websockets)
    debugprint('Opened %s of %s socket(s).' % (len(wolsockets)
                                               + len(websockets)
                                               ,len(sockets)))
    listen(sockets)
except Exception:
    errorled()
    raise
finally:
    for s in sockets:
        try:
            s.close()
        except:
            pass

