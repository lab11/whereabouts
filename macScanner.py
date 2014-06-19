#!/usr/bin/env python

# sudo ifconfig wlan0 down
# sudo iwconfig wlan0 mode monitor
# sudo ifconfig wlan0 up

from scapy.all import *
import time
import signal
import sys
from threading import Thread
import Queue
import urllib2
import json
import httplib

TOTAL_COUNT = 0
UNIQUE_COUNT = 0
TIME_DURATION = time.time()

USAGE ="""
To perform a one-time scan, specify 'test'

To perform continuous monitoring, please specify the location being monitored.
Locations should be specified in the format:
    University|Building|Room

The following locations have been seen historically:"""

LOCATION = "" # set as a input argument
MACADDR_GET_ADDR = 'http://inductor.eecs.umich.edu:8085/explore/profile/PGMR22B9wP'
MACADDR_POST_ADDR = 'http://inductor.eecs.umich.edu:8081/PGMR22B9wP'

KNOWN_DEVICES = {
        '28:cf:da:db:e9:98': 'Branden Laptop',
        '90:21:55:78:f9:c9': 'Branden Smartphone',
        'bc:ee:7b:4a:57:78': 'Neal Laptop',
        '8c:3a:e3:5d:2f:64': 'Neal Smartphone',
        '00:26:bb:07:2b:35': 'Thomas Laptop',
        '3c:ab:8e:66:40:25': 'David Smartphone',
        '8c:a9:82:ba:65:3c': 'Noah N Laptop',
        '8c:58:77:84:7c:3e': 'Noah N Smartphone',
        '14:10:9f:d4:69:cf': 'Pat Laptop',
        'a0:0b:ba:ca:78:66': '4908parrot',
        '10:68:3f:4f:9f:7f': '4908nexus4',
        '00:0c:f7:03:5f:fc': 'FrankenUbi',
        '00:04:a3:d6:41:40': '4908egg01',
        '00:25:2f:13:07:50': '4908tedmtu01',
        '00:25:2f:26:05:9d': '4908tedecc01',
        '00:17:88:09:d9:e8': '4908hue',
        'e0:b9:ba:e0:7b:7b': 'andrewsipad',
        '00:0e:f3:1f:5b:e6': '4908insteon',
        '00:12:17:31:10:7C': '4908landwaves',
        '20:aa:4b:e0:2f:73': '4908airwaves0',
        '20:aa:4b:e0:2f:74': '4908airwaves1',
        '00:18:56:2d:da:05': '4908eyefi',
        '18:b4:30:08:15:9b': '4908nest',
        '00:1d:c9:d1:d5:52': '4908weight',
        '9c:20:7b:d1:dC:15': 'fiji0',
        '9c:20:7b:d1:dC:16': 'fiji1',
        'ec:1a:59:7b:18:81': '4908wemo1',
        'ec:1a:59:7b:1c:25': '4908wemo2',
        'ec:1a:59:7b:64:2d': '4908wemo3',
        'ec:1a:59:f7:ef:79': '4908wemo4',
        'ec:1a:59:f7:ef:9d': '4908wemo5',
        'ec:1a:59:f7:eb:2d': '4908wemo6',
        'ec:1a:59:f7:a9:ed': '4908wemo7',
        'ec:1a:59:f7:f5:11': '4908wemo8',
        '00:05:CD:29:D2:80': '4908audio',
        '00:18:23:22:a2:ba': '4908video',
        '00:23:eb:dc:4b:60': '?Noah K Laptop?',
        '38:aa:3c:f6:d7:68': 'Will Smartphone',
        '40:0e:85:f1:80:8a': 'Meghan Smartphone',
        '3c:15:c2:bc:c1:68': 'Meghan Big Laptop'
        }

def main():
    global USAGE, LOCATION 
    
    # get a list of previously monitored locations
    try:
        scan_locations = get_scan_locations()
    except urllib2.URLError:
        print("Connection to inductor unavailable. Running in test mode")
        LOCATION = 'test'

    # get location
    if len(sys.argv) != 2:
        print(USAGE)
        index = 0
        for location in scan_locations:
            print("    [" + str(index) + "]: " + location)
            index += 1
        print("")
        user_input = raw_input("Select a location or enter a new one: ")

        if user_input == '':
            print("Invalid selection")
            exit()

        if user_input.isdigit():
            user_input = int(user_input)
            if 0 <= user_input < index:
                LOCATION = scan_locations[user_input]
            else:
                print("Invalid selection")
                exit()
        else:
            LOCATION = user_input
    else:
        LOCATION = sys.argv[1]

    post_to_gatd = True
    if LOCATION == 'test':
        print('Running test scans...')
        post_to_gatd = False
    
    # create thread to handle posting to GATD if desired
    msg_queue = None
    poster_thread = None
    if post_to_gatd:
        msg_queue = Queue.Queue()
        poster_thread = GATDPoster(msg_queue)

    scanner = MACScanner(queue=msg_queue, thread=poster_thread)

    while True:
        scanner.hop()
        scanner.sniff()


class MACScanner():
    # Possible wifi channels for scanning
    wifi_channels = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                    36, 38, 40, 44, 46, 48,
                    149, 151, 153, 157, 159, 161, 165]
    
    def __init__(self, sample_window=60, queue=None, print_all=False, thread=None):
        self.sample_window = sample_window
        self.msg_queue = queue
        self.print_all = print_all
        self.thread = thread

        self.channel_index = 0
        self.devices = {}

    def _getRSSI(self, pkt):
        return (ord(pkt.notdecoded[-4:-3])-256)

    def _median(self, alist):
        # sort list and find middle
        srtd = sorted(alist)
        mid = len(alist)/2
        
        if len(alist) %2 == 0:
            # take the average of the middle two
            return int(round((srtd[mid-1] + srtd[mid]) / 2.0))
        else:
            # return the middle value
            return int(round(srtd[mid]))

    def _update_device(self, mac_addr, pkt):
        global TOTAL_COUNT, UNIQUE_COUNT

        # throw out invalid data
        if mac_addr in ['ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00', None]:
            # clearly invalid MAC addresses
            return
        if self._getRSSI(pkt) == -256:
            # unreasonable RSSI, might imply an error occurred
            return
        if (mac_addr[0:5] == '33:33' or mac_addr[0:8] == '01:00:5e' or
                mac_addr[0:8] == '00:00:5e'):
            # IPv6 multicast, IPv4 multicast, and IPv4 unicast, and respectively
            return
        if (mac_addr in ['01:00:0c:cc:cc:cc', '01:00:0c:cc:cc:cd',
                '01:80:C2:00:00:00', '01:80:C2:00:00:03', '01:80:C2:00:00:0E',
                '01:80:C2:00:00:08', '01:80:C2:00:00:01', '01:80:C2:00:00:02']):
            # various multicast addresses (http://en.wikipedia.org/wiki/Multicast_address)
            return
        if (mac_addr[0:8] == 'ec:1a:59' or mac_addr[0:8] == '08:1f:f3' or
                mac_addr[0:8] == '00:23:eb'):
            # Cisco and Belkin mac addresses. Most likely correlate to routers
            #   for MWireless. This one is a little iffy to throw out...
            return

        # init device if necessary
        if mac_addr not in self.devices:
            UNIQUE_COUNT += 1
            self.devices[mac_addr] = {}
            self.devices[mac_addr]['count'] = 0
            self.devices[mac_addr]['rssi'] = {'average': -200, 'newest': -200, 'samples': {}}
        
        # save various metadata about the connection
        dev = self.devices[mac_addr]
        dev['count'] += 1
        dev['channel'] = self.wifi_channels[self.channel_index]
        current_time = time.time()
        dev['timestamp'] = current_time
        
        # save RSSI data. Only keep values from within the last minute
        for timestamp in dev['rssi']['samples'].keys():
            if float(timestamp) < (current_time - self.sample_window):
                del dev['rssi']['samples'][timestamp]
        dev['rssi']['samples'][current_time] = self._getRSSI(pkt)
        dev['rssi']['average'] = self._median(dev['rssi']['samples'].values())

        # push to message queue if it exists
        TOTAL_COUNT += 1
        if self.msg_queue != None:
            # check if thread is still alive
            if not self.thread.isAlive():
                print("Post to GATD thread died!!")
                sys.exit(1)
            # push data to thread to be posted
            self.msg_queue.put([mac_addr, dev])

    def _print_device(self, index, mac_addr):
        global KNOWN_DEVICES

        dev = self.devices[mac_addr]

        print_str = "(" + str(index) + ")" + \
                    "\tMAC: " + str(mac_addr) + \
                    "  RSSI: " + str(dev['rssi']['average']) + \
                    "  Chan: " + str(dev['channel'])

        time_diff = int(round(time.time() - dev['timestamp']))
        if time_diff < 100:
            print_str += "\tAgo: " + str(time_diff) + '  '
        else:
            print_str += "\tAgo: " + str(time_diff)

        if mac_addr in KNOWN_DEVICES:
            print_str += "\t" + str(KNOWN_DEVICES[mac_addr])

        print(print_str)

    def PacketHandler(self, pkt):
        global KNOWN_DEVICES

        if pkt.haslayer(Dot11):
            # update devices based on mac addresses in this packet
            self._update_device(pkt.addr1, pkt)
            self._update_device(pkt.addr2, pkt)

            # clear terminal screen and print dict
            os.system('cls' if os.name == 'nt' else 'clear')
            print("Time: " + time.strftime("%I:%M:%S"))

            index = 0
            if self.print_all:
                for mac_addr in copy_list:
                    index += 1
                    self._print_device(index, mac_addr)

            else:
                sorted_macs = sorted(self.devices,
                        key=lambda mac_addr: self.devices[mac_addr]['rssi']['average'],
                        reverse=True)
                other_lines = 52 - len([x for x in sorted_macs if x in KNOWN_DEVICES])

                for mac_addr in sorted_macs:
                    index += 1
                    if other_lines > 0 or mac_addr in KNOWN_DEVICES:
                        # print all labeled devices and the top remaining devices that fit on screen
                        if mac_addr not in KNOWN_DEVICES:
                            other_lines -= 1
                        self._print_device(index, mac_addr)
                        pass

    def hop(self):
            # hop to the next channel
            self.channel_index += 1
            if self.channel_index >= len(self.wifi_channels):
                self.channel_index = 0

            os.system("iwconfig wlan0 channel " + str(self.wifi_channels[self.channel_index]))
            #print("NEW CHANNEL: Channel " + str(wifi_channels[channel_index]))

    def sniff(self, timeout=1):
            # run a time-limited scan on the channel
            sniff(iface="wlan0", prn = self.PacketHandler,
                    lfilter=(lambda x: x.haslayer(Dot11)), timeout=timeout)


class GATDPoster(Thread):
    
    def __init__(self, queue):
        # init thread
        super(GATDPoster, self).__init__()
        self.daemon = True

        # init data
        self.msg_queue = queue

        # start thread
        self.start()

    def run(self):
        global LOCATION, MACADDR_POST_ADDR
        
        while True:
            # look for a packet
            [mac_addr, dev] = self.msg_queue.get()
            data = {
                    'location_str': LOCATION,
                    'mac_addr': mac_addr,
                    'rssi': dev['rssi']['newest'],
                    'avg_rssi': dev['rssi']['average'],
                    'channel': dev['channel']
                    }

            # post to GATD
            try:
                #print("Posting to GATD\n" + str(json.dumps(data)) + '\n')
                req = urllib2.Request(MACADDR_POST_ADDR)
                req.add_header('Content-Type', 'application/json')
                response = urllib2.urlopen(req, json.dumps(data))
            except (httplib.BadStatusLine, urllib2.URLError), e:
                # ignore error and carry on
                print("Failure to POST" + str(e))


def get_scan_locations():
    global MACADDR_GET_ADDR

    # query GATD explorer to find scan locations
    req = urllib2.Request(MACADDR_GET_ADDR)
    response = urllib2.urlopen(req)
    json_data = json.loads(response.read())

    if 'location_str' in json_data:
        return json_data['location_str'].keys()
    else:
        return ['None']

def sigint_handler(signum, frame):
    # exit the program if we get a CTRL-C
    global TOTAL_COUNT, UNIQUE_COUNT, TIME_DURATION
    print("\n")
    print("Unique Devices: " + str(UNIQUE_COUNT))
    print("Total Packets Scanned: " + str(TOTAL_COUNT))
    print("Total Scan Time: " + str(int(round(time.time() - TIME_DURATION))) + " seconds")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, sigint_handler)
    main()
