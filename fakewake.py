#! /usr/bin/env python3
##
## This software is supplied "as is" with no warranties either expressed or implied.
##
## It worked for me but your mileage may vary.
##
## For non-comercial use only.

# imports
import argparse
import configparser
import gpiozero
import grp
import logging
import os
import pwd
import select
import socket
import io
import struct
import sys
import time
import threading


# function definitiona start here

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

    logging.debug('HOSTS_ALLOW %s' % HOSTS_ALLOW)
    logging.debug('HOSTS_DENY %s' % HOSTS_DENY)
    # make sure we have a string
    ipaddr = str(ipaddr)
    logging.debug('ipaddr to check %s' % ipaddr)

    if ipaddr in HOSTS_ALLOW:
        # always allowed
        return True

    if '*' in HOSTS_DENY:
        # all denied
        return False

    if ipaddr in HOSTS_DENY:
        # allow all except denied
        return False

    # otherwise
    # default action
    return True


# daemonize
# based on the python recipe at
#   http://code.activestate.com/recipes/278731-creating-a-daemon-the-python-way

def _daemonize_me():
    umask = 0
    workingdir = '/'
    maxfd = 1024
    if (hasattr(os, 'devnull')):
        devnull = os.devnull
    else:
        devnull = '/dev/null'

    try:
        pid = os.fork()
    except OSError as e:
        raise Exception('%s [%d]' % (e.strerror, e.errno))

    if pid == 0:
        # we are the first child
        os.setsid()
        try:
            pid = os.fork()
        except OSError as e:
            raise Exception('%s [%d]' % (e.strerror, e.errno))
        if pid == 0:
            # second child
            os.chdir(workingdir)
            os.umask(umask)
        else:
            os._exit(0)
    else:
        os._exit(0)
    # close all open file descriptors
    try:
        mfd = os.sysconf('SC_OPEN_MAX')
    except (AttributeError, ValueError):
        mfd=maxfd
    for fd in range(0, mfd):
        try:
            os.close(fd)
        except OSError:
            pass # ignore as it wasn't open anyway

    # redirect stdio
    os.open(devnull, os.O_RDWR) # stdin
    os.dup2(0, 1) # stdout
    os.dup2(0, 2) # stderr

def pack_mac(split_mac_address):
    # given a split MAC address return it packed for sending/receiving

    packed = struct.pack(b'!BBBBBB',
                         int(split_mac_address[0], 16),
                         int(split_mac_address[1], 16),
                         int(split_mac_address[2], 16),
                         int(split_mac_address[3], 16),
                         int(split_mac_address[4], 16),
                         int(split_mac_address[5], 16))
    return packed

def press_button(button, duration):
    # button is a gpiozero digital output object
    # duration in seconds
    #
    # time check prevents spamming of the switches
    global last_action_time
    
    if button is None:
        return

    current_time = time.time()
    if current_time > last_action_time + MIN_INTERVAL:
        logging.info('%s button pressed for %s seconds at %s',
                     BUTTON_NAMES[button.pin.number], duration,
                     time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time)))
        last_action_time = current_time
        button.on()
        time.sleep(duration)
        button.off()
    else:
        logging.debug('Too soon after last action.')

def pinger(targets, interval):
    # thread to ping target system and set result accordingly
    global PINGABLE
    
    logging.debug('Ping targets: %s' %targets)

    # create ping object
    pingthings = {}
    for t in targets:
        pingthings[t] = gpiozero.PingServer(t)
    logging.debug(pingthings)
    # ~ logging.debug('Creating pinger object for %s' % target)
    # ~ pingthing = gpiozero.PingServer(target)
    # ~ # ensure we have an apropriate value
    # ~ if pingthing.value:
        # ~ PINGABLE = 'Yes'
    # ~ else:
        # ~ PINGABLE = 'No'
    # keep pinging
    # for an "and" combination of multiple targets
    while stop_threads == False:
        result = '<br>'
        for p in pingthings:
            result += '%s: %s<br>' % (p,('No','Yes')[pingthings[p].value])
        PINGABLE = result
        time.sleep(interval)
    # cleanup
    for p in pingthings:
        pingthings[p].close()
    logging.debug('Exiting')

def make_packet(mac_address):
    # given a mac address return a wol magic packet

    wol_header = b'\xff' * 6
    parts = mac_address.split(':')

    if len(parts) != 6:
        return None

    return wol_header + pack_mac(parts) * 16
    
def wol_listener():
    # wake on lan listerner(s)
    # this is about as basic as it can get
    # not fully compliant with WOL spec as packets will only been seen when sent as UDP to a know port
    # (usually 7 and/or 9)
    # this will not wake a PC from sleep if the PSU remains fully on
    # true WOL requires examining every ethernet frame received by the network interface

    global WOL_ENABLED, WOL_SECUREON, privs_droppable

    # create magic packets
    logging.debug('Creating magic packets')
    magic_packets = {}
    magic_packets['wake'] = make_packet(WOL_WAKE_MAC_ADDRESS)
    magic_packets['shutdown'] = make_packet(WOL_SHUTDOWN_MAC_ADDRESS)
    magic_packets['reset'] = make_packet(WOL_RESET_MAC_ADDRESS)
    magic_packets['forceoff'] = make_packet(WOL_FORCEOFF_MAC_ADDRESS)
    magic_packets['aux1'] = make_packet(WOL_AUX1_MAC_ADDRESS)
    magic_packets['aux2'] = make_packet(WOL_AUX2_MAC_ADDRESS)

    empty_packet_count = 0
    for packet in list(magic_packets.values()):
        if packet is None:
            empty_packet_count += 1
    
    # check we have something to listen for and ports to listen on
    if (empty_packet_count == len(magic_packets)
         or len(WOL_PORTS) == 0 ):
        WOL_ENABLED = False
        logging.warning('Nothing to listen for. Exiting and disabling WOL listener.')
        privs_droppable[WOL_DROPPABLE] = True
        return
    
    # create and start listeners
    logging.debug('Creating listeners')
    listeners = []
    for port in WOL_PORTS:
        try:
            logging.debug('Trying on port %s' % port)
            listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listener.setblocking(0)
            listener.bind(('', port))
            listeners.append(listener)
            logging.debug('Success ')
        except Exception as e:
            logging.error('Failed to start WOL listener on port %s %s', port, str(e))
    if len(listeners) ==  0:
        logging.error('Failed to start any WOL listeners. Exiting thread and disabling WOL listener.')
        WOL_ENABLED = False
        privs_droppable[WOL_DROPPABLE] = True
        return

    logging.debug('Started %s listener(s)' % len(listeners))
    privs_droppable[WOL_DROPPABLE] = True

    while stop_threads == False:
        # now we can actually do some listening
        r, w, e = select.select(listeners, [], [], 0)
        for s in r:
            inc = ''
            inc, sender = s.recvfrom(1024)
            logging.debug('data received from %s' % sender[0])
            logging.debug('\t%s' % inc)
            # validate host
            if valid_host(sender[0]) == False:
                logging.debug('invalid sender. Ignoring packet.')
                continue
            for k in magic_packets:
                logging.debug('Recieved:\n\t%s\nMatching against:\n\t%s' % (inc, magic_packets[k]))
                if (magic_packets[k] is not None
                    and magic_packets[k] in inc):
                    logging.debug('Matched %s' % k)
                    try:
                        # it's a magic packet we want to handle
                        if k in ('wake', 'shutdown', 'forceoff'):
                            logging.debug('Setting button to POWER_SWITCH')
                            target_button = POWER_SWITCH
                        elif k == 'reset':RESET_SWITCH
                        elif k == 'aux1':
                            target_button = AUX1
                        elif k == 'aux2':
                            target_button = AUX2
                        else:
                            # reserved for future use
                            logging.debug('You should never see this')
                    except NameError:
                        logging.exception('No pin configured for function.')
                        target_button = None
                    if k == 'forceoff':
                        target_duration = LONG_PRESS
                    else:
                        target_duration = SHORT_PRESS
                    logging.debug('Press duration set to %s' % target_duration)
                    go_nogo = False
                    if (k == 'wake'
                        and PSU_SENSE.is_active == False):
                        go_nogo = True
                    if (k in ('shutdown', 'forceoff', 'reset')
                        and PSU_SENSE.is_active == True):
                        go_nogo = True
                    if k in ('aux1', 'aux2'):
                        go_nogo = True

                    if go_nogo:
                        # press button here
                        press_button(target_button, target_duration)
                    else:
                        logging.debug('%s packet ignored due to current PSU state' % k)
                else:
                    logging.debug('Recieved data does not match %s packet' % k)
                break
        time.sleep(0.1)

    for listener in listeners:
        listener.close()
    logging.debug('exiting')

def webserver(host, port):
    # simple web server for control page
    # currently has no security so anyone who finds it can use it
    #
    # this is also far from a complete webserver
    #
    # yes, I'm aware I could use BaseHTTPServer
    # but I'm not sure how that copes with globals, threading,
    # dropping root privs, and non-blocking sockets

    global last_action_time, privs_droppable

    base_header = 'HTTP/1.0 '
    ok_header = '200 OK\n\n'
    html_header = '<!DOCTYPE HTML>\n<html><head><title>fakewake</title>\n'
    clacks_header = '<meta http-equiv="X-Clacks-Overhead" content="GNU Terry Pratchett" />\n'
    refresh_header = '<meta http-equiv="refresh" content="%s;/">' % WEBSERVER_RELOAD_DELAY
    end_header = '</head><body>'

    error403 = base_header + ok_header + html_header + clacks_header + end_header
    error403 += '<h2>403 Forbidden</h2></body></html>'
    error404 = base_header + ok_header + html_header + clacks_header + end_header
    error404 += '<h2>This space unintetionally left blank</h2></body></html>'
    error405 = base_header + '405 Method Not Allowed\n' + html_header + clacks_header + end_header
    error405 += '<h2>405 Method Not Allowed</h2></body></html>'
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    logging.debug('binding to %s:%s' % (host,port))
    server_socket.bind((host,port))
    server_socket.listen(5)
    privs_droppable[WEB_DROPPABLE] = True
    logging.debug('started listening')
    server_socket.setblocking(0)
    while stop_threads == False:
        r, w, e = select.select([server_socket],[],[],0)
        for s in r:
            if s == server_socket:
                # accept socket and handle request
                client_socket, client_address = server_socket.accept()
                # validate host
                if valid_host(client_address[0]) == False:
                    logging.info('Access attempted from blocked host %s(%s)' % (client_address[0],
                                                                                socket.gethostbyaddr(client_address[0])[0]))
                    client_socket.sendall(error403)
                    client_socket.shutdown(socket.SHUT_RDWR)
                    client_socket.close
                    continue
                # receive request. This may block
                request = client_socket.recv(1024).decode()
                logging.info('Connection from ' + client_address[0])
                logging.debug('Parsing reguest')
                # parse request
                for line in request.splitlines():
                    logging.debug(line)
                    prefix = line.split(' ',1)[0]
                    if prefix in ('POST', 'HEAD', 'PUT', 'DELETE',
                                    'OPTIONS', 'CONNECT'):
                        logging.debug('Sending Error 405')
                        client_socket.sendall(error405.encode())
                    elif prefix != 'GET':
                        # don't know and don't care what this is
                        pass
                    else:
                        # must be a GET request
                        method, url, trailer = line.split()
                        # need this due to form/button hack in html code
                        url = url.split('?')[0]
                        if url not in ('/', '/power', '/forcepower','/reset','/config', '/log'):
                            client_socket.sendall(error404.encode())
                        elif url == '/log':
                            # show log file
                            logging.debug('Sending log file(%s)' % log_file)
                            reply = base_header + ok_header
                            try:
                                lf = open(log_file, 'r')
                                reply += lf.read()
                                lf.close()
                            except KeyboardInterrupt:
                                raise
                            except IOError as e:
                                reply += str(e)
                            client_socket.sendall(reply.encode())
                        elif url == '/config':
                            # show config
                            reply = base_header + ok_header
                            current_config = io.StringIO()
                            config.write(current_config)
                            reply += current_config.getvalue()
                            current_config.close()
                            # send replycfg
                            logging.debug('Sending config')
                            client_socket.sendall(reply.encode())
                        elif url == '/':
                            # assemble page
                            if time.time() > last_action_time + MIN_INTERVAL:
                                button_state = ''
                            else:
                                button_state = 'disabled'
                            reply = base_header + ok_header + html_header + clacks_header + refresh_header + end_header
                            reply += '<b>PSU State:</b> '
                            if PSU_SENSE_ENABLED:
                                if PSU_SENSE.is_active:
                                    reply += 'On'
                                else:
                                    reply += 'Off/Standby'
                            else:
                                reply += 'Unknown'
                            reply += '<br><b>Pingable:</b> %s' % PINGABLE
                            if POWER_ENABLED:
                                reply += '<center><form action="/power" method="get">'
                                reply += '<input type="submit" value="Power On/Off" %s></form><br>' % button_state
                                reply += '<form action="/forcepower" method="get">'
                                reply += '<input type="submit" value="Force Power Off" %s></form><br>' % button_state
                            if RESET_ENABLED:
                                reply += '<form action="/reset" method="get">'
                                reply += '<input type="submit" value="Reset" %s></form><br>' % button_state
                            if AUX1_ENABLED:
                                reply += '<form action="/aux1" method="get">'
                                reply += '<input type="submit" value="Aux 1" %s></form><br>' % button_state
                            if AUX2_ENABLED:
                                reply += '<form action="/aux2" method="get">'
                                reply += '<input type="submit" value="Aux 2" %s></form><br>' % button_state
                            reply += '</center></body></html>'
                            # send reply
                            client_socket.sendall(reply.encode())
                        else:
                            # send reply
                            # this is the same for all actions
                            reply = base_header + ok_header + html_header + clacks_header + refresh_header
                            reply += 'Working. Please wait...'
                            reply += '<center><form action="/" method="get">'
                            reply += '<input type="submit" value="Continue">'
                            reply += '</form></center></body></html>'
                            client_socket.sendall(reply.encode())
                            # do action
                            if url == '/power' and POWER_ENABLED:
                                logging.debug('Pushing Power Button')
                                press_button(POWER_SWITCH, SHORT_PRESS)
                            if url =='/forcepower' and POWER_ENABLED and PSU_SENSE.is_active:
                                logging.debug('Long Push on Power Button')
                                press_button(POWER_SWITCH, LONG_PRESS)
                            if url =='/reset' and RESET_ENABLED and PSU_SENSE.is_active:
                                logging.debug('Pushing Reset Button')
                                press_button(RESET_SWITCH, SHORT_PRESS)
                            if url =='/aux1' and AUX1_ENABLED:
                                logging.debug('Firing aux1')
                                press_button(AUX1, SHORT_PRESS)
                            if url =='/aux2' and AUX2_ENABLED:
                                logging.debug('Firing aux2')
                                press_button(AUX2, SHORT_PRESS)
                client_socket.close()
                reply = None
        # reduce cpu load
        time.sleep(0.1)
    server_socket.close()
    logging.debug('exiting')

def start_pinger():
    global PINGABLE
    PINGABLE = 'Unknown'
    if PINGER_ENABLED:
        logging.debug('(re)starting Pinger')
        ping_thread = threading.Thread(name='pinger',
                                       target=pinger,
                                       args=(TARGET_IDS, PING_INTERVAL))
        ping_thread.start()
    else:
        ping_thread = None
    return ping_thread

def start_webserver():
    global privs_droppable
    if WEBSERVER_ENABLED:
        logging.debug('(re)starting Webserver')
        webserver_thread = threading.Thread(name='webserver',
                                            target=webserver,
                                            args=(WEBSERVER_HOST,WEBSERVER_PORT))
        webserver_thread.start()
    else:
        webserver_thread = None
        privs_droppable[WEB_DROPPABLE] = True
    return webserver_thread

def start_wol():
    global privs_droppable
    if WOL_ENABLED:
        logging.debug('(re)starting wol listener')
        wol_thread = threading.Thread(name='wol_listener',
                                      target=wol_listener)
        wol_thread.start()
    else:
        wol_thread = None
        privs_droppable[WOL_DROPPABLE] = True
    return wol_thread


## now we can do something...
if __name__ == '__main__':

    # globals
    #   default config
    #   fed to config parser
    default_config = {'power':'23',
                      'reset':'24',
                      'psu_sense':'25',
                      'short':'0.1',
                      'long':'5.0',
                      'min_interval':'180',
                      'web_enabled':'True',
                      'host':'',
                      'web_port':'8080',
                      'reload_delay':'15',
                      'wol_enabled':'False',
                      'wol_ports':'7, 9, 7491',
                      'wake_mac':'',
                      'shutdown_mac':'',
                      'reset_mac':'',
                      'forceoff_mac':'',
                      'ping_enabled':'True',
                      'target':'',
                      'interval':'1',
                      'restart':'True',
                      'aux1':'0',
                      'aux2':'0',
                      'aux1_mac':'',
                      'aux2_mac':'',
                      'hosts_allow':'',
                      'hosts_deny':'',
                      'psu_sense_active_low':False}
    # pinger
    PINGABLE = 'Unknown'

    #  elevated privilages management
    DROP_PRIVS = True
    WEB_DROPPABLE = 0
    WOL_DROPPABLE = 1
    PRIVS_NAME = 'nobody'
    PRIVS_GROUP = 'nogroup'
    privs_dropped = False
    privs_droppable = {WEB_DROPPABLE: False, WOL_DROPPABLE: False}

    # cmd line arguments
    #   need to do this here as it may affect logging config
    #   and whether we should continue to run in the foreground
    cmd_parser = argparse.ArgumentParser(description='Wake on LAN daemon. Controls power on/off for a PC connected to gpio.',
                                         epilog='If -c is not specified the internal defaults will be used')
    cmd_parser.add_argument('--debug', help='enabled debug output to logfile',
                            action='store_true', default=False)
    cmd_parser.add_argument('-c','--config', help='load config from specified file.',
                            default='')
    cmd_parser.add_argument('-N','--nodaemon',
                            help='do not daemonise. Run in foreground instead.',
                            action = 'store_true',
                            default=False)
    cmd_args = cmd_parser.parse_args()
    #  preprocess config file name if present
    if cmd_args.config != '':
        cmd_args.config = os.path.abspath(cmd_args.config)

    # daemonise
    if cmd_args.nodaemon == False:
        _daemonize_me()
    
    # set up logging
    log_file = '/tmp/fakewake.log'
    log_format = '%(asctime)s:%(levelname)s:%(threadName)s:%(message)s'
    log_filemode = 'w'
    #   manage log files
    try:
        os.rename(log_file +'2', log_file +'3')
    except OSError:
        pass
    try:
        os.rename(log_file, log_file +'2')
    except OSError:
        pass
    #   base logger
    if cmd_args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level,
                        filename=log_file, filemode=log_filemode,
                        format=log_format)
    #   set permissions on log file
    try:
        os.chmod(log_file, 0o666)
    except OSError:
        pass
    #   log errors and warnings to stderr
    stderr_logger = logging.StreamHandler(sys.stderr)
    stderr_formatter = logging.Formatter('fakewake:%(levelname)s:%(message)s')
    stderr_logger.setLevel(logging.WARNING)
    stderr_logger.setFormatter(stderr_formatter)
    logging.getLogger('').addHandler(stderr_logger)
    #   uncomment to enable logging to console
    console_logger = logging.StreamHandler()
    console_formatter = logging.Formatter(log_format)
    console_logger.setFormatter(console_formatter)
    logging.getLogger('').addHandler(console_logger)

    #   just in case there's a running tail -f on the log file
    #   it's a hack, I know.
    logging.info('\x1b[2J\x1b[H')

    #   log pid
    logging.info('My pid: %s' % os.getpid())
    # read config
    logging.debug('reading config file')
    # this is probably abusing the defaults mechanism...
    config = configparser.ConfigParser(default_config)
    try:
        t = config.read(cmd_args.config)
    except configparser.Error as e:
        # error when parsing config file
        msg = 'Error parsing config file %s: %s' % (cmd_args.config, str(e))
        logging.critical(msg)
        logging.critical('Exiting.')
        sys.exit(msg)
    if len(t) == 0 and cmd_args.config != '':
        # couldn't open config file
        msg = 'Unable to open config file ' + cmd_args.config
        logging.critical(msg)
        logging.critical('Exiting.')
        sys.exit(msg)
        
    try:
        POWER_PIN = config.getint('pins', 'power')
        RESET_PIN = config.getint('pins','reset')
        PSU_SENSE_PIN = config.getint('pins', 'psu_sense')
        PSU_SENSE_ACTIVE_LOW = config.getboolean('pins', 'psu_sense_active_low')
        AUX1_PIN = config.getint('pins', 'aux1')
        AUX2_PIN = config.getint('pins', 'aux2')
    except configparser.NoSectionError:
        POWER_PIN = int(default_config['power'])
        RESET_PIN = int(default_config['reset'])
        PSU_SENSE_PIN = int(default_config['psu_sense'])
        PSU_SENSE_ACTIVE_LOW = default_config['psu_sense_active_low']
        AUX1_PIN = int(default_config['aux1'])
        AUX2_PIN = int(default_config['aux2'])
    try:
        SHORT_PRESS = config.getfloat('timings', 'short')
        LONG_PRESS = config.getfloat('timings', 'long')
        MIN_INTERVAL = config.getfloat('timings','min_interval')
    except configparser.NoSectionError:
        SHORT_PRESS = float(default_config['short'])
        LONG_PRESS = float(default_config['long'])
        MIN_INTERVAL = float(default_config['min_interval'])
    try:
        WEBSERVER_ENABLED = config.getboolean('webserver','web_enabled')
        WEBSERVER_HOST = config.get('webserver','host')
        WEBSERVER_PORT = config.getint('webserver', 'web_port')
        WEBSERVER_RELOAD_DELAY = config.get('webserver','reload_delay')
    except configparser.NoSectionError:
        WEBSERVER_ENABLED = bool(default_config['web_enabled'])
        WEBSERVER_HOST = default_config['host']
        WEBSERVER_PORT = int(default_config['web_port'])
        WEBSERVER_RELOAD_DELAY = default_config['reload_delay']
    try:
        WOL_ENABLED = config.getboolean('wol', 'wol_enabled')
        RAW_WOL_PORTS = config.get('wol', 'wol_ports')
        WOL_WAKE_MAC_ADDRESS = config.get('wol', 'wake_mac')
        WOL_SHUTDOWN_MAC_ADDRESS = config.get('wol', 'shutdown_mac')
        WOL_RESET_MAC_ADDRESS = config.get('wol', 'forceoff_mac')
        WOL_FORCEOFF_MAC_ADDRESS = config.get('wol', 'reset_mac')
        WOL_AUX1_MAC_ADDRESS = config.get('wol', 'aux1_mac')
        WOL_AUX2_MAC_ADDRESS = config.get('wol', 'aux2_mac')
    except configparser.NoSectionError:
        WOL_ENABLED = bool(default_config['wol_enabled'])
        RAW_WOL_PORTS = default_config['wol_ports']
        WOL_WAKE_MAC_ADDRESS = default_config['wake_mac']
        WOL_SHUTDOWN_MAC_ADDRESS = default_config['shutdown_mac']
        WOL_RESET_MAC_ADDRESS = default_config['forceoff_mac']
        WOL_FORCEOFF_MAC_ADDRESS = default_config['reset_mac']
        WOL_AUX1_MAC_ADDRESS = default_config['aux1_mac']
        WOL_AUX1_MAC_ADDRESS = default_config['aux1_mac']
    # parse RAW_WOL_PORTS
    WOL_PORTS = []
    for t in RAW_WOL_PORTS.split(','):
        t.strip()
        WOL_PORTS.append(int(t))
    try:
        PINGER_ENABLED = config.getboolean('pinger', 'pinger_enabled')
        TARGET_IDS = config.get('pinger', 'target').strip().split(',')
        PING_INTERVAL = config.getfloat('pinger', 'interval')
    except configparser.NoSectionError:
        PINGER_ENABLED = bool(default_config['pinger_enabled'])
        TARGET_IDS = default_config['target'].strip().split(',')
        if TARGET_IDS is None or len(TARGET_IDS) == 0:
            PINGER_ENABLED = False
        PING_INTERVAL = float(default_config['interval'])
    try:
        RESTART_THREADS = config.getboolean('threads', 'restart')
    except configparser.NoSectionError:
        RESTART_THREADS = bool(default_config['restart'])
    try:
        RAW_HOSTS_ALLOW = config.get('security','hosts_allow')
        RAW_HOSTS_DENY = config.get('security','hosts_deny')
    except configparser.NoSectionError:
        RAW_HOSTS_ALLOW = default_config['hosts_allow']
        RAW_HOSTS_DENY = default_config['hosts_deny']
    # parse RAW host lists
    HOSTS_ALLOW = []
    for t in RAW_HOSTS_ALLOW.split(','):
        t.strip
        HOSTS_ALLOW.append(t)
    HOSTS_DENY = []
    for t in RAW_HOSTS_DENY.split(','):
        t.strip
        HOSTS_DENY.append(t)

    #  enable/disable flags
    POWER_ENABLED = bool(POWER_PIN)
    RESET_ENABLED = bool(RESET_PIN)
    PSU_SENSE_ENABLED = bool(PSU_SENSE_PIN)
    AUX1_ENABLED = bool(AUX1_PIN)
    AUX2_ENABLED = bool(AUX2_PIN)
    if not PSU_SENSE_ENABLED:
        # without knowing the PSU state WOL is unpredictable
        # so disable it
        logging.warning('No pin specified for PSU_SENSE. WOL support disabled')
        WOL_ENABLED = False

    #  button names
    BUTTON_NAMES = {POWER_PIN: 'Power', RESET_PIN: 'Reset', AUX1_PIN:'AUX1', AUX2_PIN:'AUX2'}
    
    try:
        # create gpio objects
        logging.debug('Creating gpiozero objects')
        if POWER_ENABLED:
            logging.debug('  Power switch')
            POWER_SWITCH = gpiozero.DigitalOutputDevice(POWER_PIN,active_high=True,
                                                        initial_value=False)

        if RESET_ENABLED:
            logging.debug('  Reset switch')
            RESET_SWITCH = gpiozero.DigitalOutputDevice(RESET_PIN,active_high=True,
                                                        initial_value=False)

        if PSU_SENSE_ENABLED:
            logging.debug('  PSU sense')
            PSU_SENSE = gpiozero.DigitalInputDevice(PSU_SENSE_PIN,
                                                    pull_up=PSU_SENSE_ACTIVE_LOW)

        if AUX1_ENABLED:
            logging.debug('  aux 1')
            AUX1 = gpiozero.DigitalOutputDevice(AUX1_PIN,active_high=True,
                                                        initial_value=False)
        if AUX2_ENABLED:
            logging.debug('  aux 2')
            AUX2 = gpiozero.DigitalOutputDevice(AUX2_PIN,active_high=True,
                                                        initial_value=False)

        # initalise timer
        last_action_time = time.time() - MIN_INTERVAL

        # start threads
        stop_threads = False
        #   pinger
        ping_thread = start_pinger()
        #   webserver
        webserver_thread = start_webserver()
        #   wol
        wol_thread = start_wol()

        # keep running
        # short delay time initially to allow dropping privileges a.s.a.p
        if DROP_PRIVS:
            loop_delay = 0.01
        else:
            loop_delay = 0.5
        logging.debug('entering main loop')
        while True:
            current_uid = os.getuid()
            current_uname = pwd.getpwuid(current_uid)[0]
            current_gid = os.getgid()
            current_gname = grp.getgrgid(current_gid)[0]
            if (DROP_PRIVS == True
                and privs_dropped == False
                and privs_droppable[WEB_DROPPABLE] == True
                and privs_droppable[WOL_DROPPABLE] == True):
                # can drop privs
                if current_uid == 0:
                    # root
                    logging.debug('Running as root. Attempting to drop privileges')
                    drop_failed = False
                    target_uid = pwd.getpwnam(PRIVS_NAME)[2]
                    target_gid = grp.getgrnam(PRIVS_GROUP)[2]
                    # log file
                    try:
                        os.chown(log_file, target_uid, target_gid)
                    except OSError:
                        logging.debug('Unabled to change ownership of log file to %s:%s', PRIVS_NAME, PRIVS_GROUP)
                    # group ID
                    try:
                        os.setegid(target_gid)
                    except OSError as e:
                        drop_failed = True
                        logging.debug('Unabled to set gid to %s %s' % (PRIVS_GROUP, e))
                    # user ID
                    try:
                        os.seteuid(target_uid)
                    except OSError as e:
                        drop_failed = True
                        logging.debug('Unabled to set uid to %s %s' % (PRIVS_NAME, e))
                    # umask
                    try:
                        os.umask(0o77)
                    except OSError as e:
                        drop_failed = True
                        logging.debug('Unabled to set umask to 077 %s' % (PRIVS_NAME, e))
                    # update logs
                    if drop_failed:
                        logging.warning('Failed to drop root priviliges.')
                    else:
                        logging.debug('Success. Now running as %s:%s' % (PRIVS_NAME, PRIVS_GROUP))
                else:
                    # not root
                    logging.debug('Currently running as user %s:%s. No need to drop privileges'
                                  % (current_uname, current_gname))
                # set this even on failure so we don't keep trying
                # and hogging the cpu
                privs_dropped = True
                loop_delay = 0.5

            # check for dead threads and restart
            # webserver and wol threads will not restart when using ports < 1024
            # once privileges have been dropped
            if ping_thread is not None and ping_thread.isAlive() == False:
                if RESTART_THREADS:
                    ping_thread = start_pinger()
                else:
                    logging.warning('Pinger thread has died.')
                    PINGABLE = 'Unknown'
            if webserver_thread is not None and webserver_thread.isAlive() == False:
                if RESTART_THREADS:
                    webserver_thread = start_webserver()
                else:
                    logging.critical('Webserver thread has died. Exiting')
                    break
            if wol_thread is not None and wol_thread.isAlive() == False:
                if RESTART_THREADS:
                    wol_thread = start_wol()
                else:
                    logging.critical('WOL listener thread has died. Exiting')
                    break
            
            time.sleep(loop_delay)
            
    finally:
        # cleanup code
        logging.debug('cleaning up')
        logging.debug('stopping threads')
        stop_threads = True
        logging.debug('Freeing GPIO')
        try:
            POWER_SWITCH.close()
        except:
            pass
        try:
            RESET_SWITCH.close()
        except:
            pass
        try:
            AUX1.close()
        except:
            pass
        try:
            AUX2.close()
        except:
            pass

