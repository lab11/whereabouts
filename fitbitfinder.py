#!/usr/bin/env python2

# Script to find fitbits
#   Finds Fitbit IDs and RSSI to the fitbit
#   Uploads data to GATD for use by other programs
#   Can also be called in TEST mode to determine fitbit IDs
#
# Uses Galileo for fitbit base station interactions
#   https://bitbucket.org/benallard/galileo

import sys
import uuid
from ctypes import c_byte

import IPy
import json
import sys
from threading import Thread
from time import sleep
from time import strftime

try:
    from galileo import (PERMISSION_DENIED_HELP, FitBitDongle,
            TimeoutError, NoDongleException, PermissionDeniedException,
            FitbitClient, a2t)
except ImportError:
    print("Unable to find the Galileo Library")
    print("    sudo pip install galileo")
    exit()

try:
    import socketIO_client as sioc
except ImportError:
    print('Could not import the socket.io client library.')
    print('sudo pip install socketIO-client')
    sys.exit(1)

import logging
logging.basicConfig()

DEVICE_MAP_FILE = "device-map.json"
LOCATION = ""
query = {'profile_id': 'U8H29zqH0i',
         'address': None} #specified in main once location is known
stream_namespace = None

USAGE = """
Please specify location being monitored.

if no door sensor is present at the specified location, 
the program defaults to polling periodically.

Door sensors are available in the following locations:
"""

# gets deployment location, picks door-triggered or polling monitor
# depending on whether there is a door sensor available.
# it would be nice to generalize this trigger idea in the future.
def main():
    global LOCATION
    global stream_namespace
    global usage

    SOCKETIO_HOST      = 'inductor.eecs.umich.edu'
    SOCKETIO_PORT      = 8082
    SOCKETIO_NAMESPACE = 'stream'

    LOCATION = "" #Get this as a system argument
    DOOR_TRIGGERED = False #Get this as a system argument

    door_sensors = get_door_sensors()

#XXX: Update this to allow a TEST function
    # get location
    if len(sys.argv) != 2:
        print(USAGE)
        for sensor in door_sensors:
            print("    " + sensor['location'])
        print("")
        exit()
    else:
        LOCATION = sys.argv[1]

    # if location has door sensor, trigger on it
    for sensor in door_sensors:
        if sensor['location'] == LOCATION:
            DOOR_TRIGGERED = True
            query['address'] = sensor['device_addr']
    
    # door/gatd triggered logic
    if DOOR_TRIGGERED:
        print("Starting door-triggered monitor")
        socketIO = sioc.SocketIO(SOCKETIO_HOST, SOCKETIO_PORT)
        stream_namespace = socketIO.define(EventDrivenMonitor,
            '/{}'.format(SOCKETIO_NAMESPACE))
        socketIO.wait()

    # periodic polling only
    else:
        print("Starting polling monitor")
        PollingMonitor(30*60) # poll every 30 mins + time to find devices
    while(True):
        pass

#XXX: Think about the best way to determine Door Devices
def get_door_sensors():
    door_sensors = []
    f = open(DEVICE_MAP_FILE)
    contents = f.read()
    f.close()
    contents = contents.replace("\n", "")
    contents = contents.replace("\t", "")
    device_maps = json.loads(contents)
    for device_map in device_maps:
        if device_map["descr"] == "door sensor":
            door_sensors.append(device_map)
    return door_sensors    

def sanitize(device_id):
    return device_id.replace(":", "").upper()

def cur_datetime():
    return strftime("%m/%d/%Y %H:%M")

def get_real_name(uniqname):
    real_name = "Unknown Name"
    f = open(DEVICE_MAP_FILE)
    contents = f.read()
    f.close()
    contents = contents.replace("\n", "")
    contents = contents.replace("\t", "")
    device_maps = json.loads(contents)
    for device_map in device_maps:
        if "uniqname" in device_map and device_map["uniqname"] == uniqname:
            real_name = device_map["owner"]
    return real_name

#XXX: Finish this
def post_to_gatd(data):
    # This is the post address for fitbitLocator
    req = urllib2.Request('http://inductor.eecs.umich.edu:8081/dwgY2s6mEu')
    response = urllib2.urlopen(req, data)

class FitbitMonitor():
    
    def update(self):
        # check for present fitbits.
        present_fitbits = self.get_present_fitbits()
        # send data to GATD
        print("Send things to GATD\n Send? " + str(present_fitbits))

    def get_present_fitbits(self):
        present_fitbits = {}
        for i in range(3):
            fitbit_data = self.discover_fitbits()
            # if timeout, try again
            if fitbit_data == None:
                i = i-1
            # otherwise merge dicts, keeping original RSSI value
            else:
                present_fitbits = dict(fitbit_data.items() + present_fitbits.items())
        return present_fitbits
        
    def discover_fitbits(self):
        dongle = FitBitDongle()
        try:
            dongle.setup()
        except NoDongleException:
            print("No fitbit base station connected, aborting")
            return
        except PermissionDeniedException:
            print(PERMISSION_DENIED_HELP)
            return

        fitbit = FitbitClient(dongle)
        fitbit.disconnect()
        fitbit.getDongleInfo()
        
        try:
            trackers = [t for t in self.discovery(dongle)]

        except TimeoutError:
            print ("Timeout trying to discover trackers")
            return
        except PermissionDeniedException:
            print PERMISSION_DENIED_HELP
            return

        return dict(trackers)

    def discovery(self, dongle):
        dongle.ctrl_write([0x1a, 4, 0xba, 0x56, 0x89, 0xa6, 0xfa, 0xbf,
                           0xa2, 0xbd, 1, 0x46, 0x7d, 0x6e, 0, 0,
                           0xab, 0xad, 0, 0xfb, 1, 0xfb, 2, 0xfb,
                           0xa0, 0x0f, 0, 0xd3, 0, 0, 0, 0])
        dongle.ctrl_read() # StartDiscovery
        d = dongle.ctrl_read(4000)
        while d[0] != 3:
            ID = sanitize(a2t(list(d[2:8])))
            RSSI = c_byte(d[9]).value
            yield [ID, RSSI]
            d = dongle.ctrl_read(4000)

        # tracker found, cancel discovery
        dongle.ctrl_write([2, 5])
        dongle.ctrl_read() # CancelDiscovery



# looks for fibit data after a door event occurs
class EventDrivenMonitor (sioc.BaseNamespace, FitbitMonitor):
    
    def on_reconnect (self):
        if 'time' in query:
            del query['time']
        stream_namespace.emit('query', query)

    def on_connect (self):
        # Always run one check at startup
        self.update()
        stream_namespace.emit('query', query)

    def on_data (self, *args):
        pkt = args[0]
        msg_type = pkt['type']
        print(cur_datetime() + ": " + pkt['type'].replace('_', ' ').capitalize() + " (" + str(LOCATION) + ")")
        # people leaving
        if msg_type == 'door_close':
            self.update() # enough latency due to multiple checks that they have enough time to escape
        # people entering. Covers folks who didn't swipe their RFID card (multiple people, keys, etc.)
        elif msg_type == 'door_open':
            self.update()
        # people entering. Covers the person who carded in (way faster than finding fitbit)
        elif pkt['type'] == 'rfid':
            person = get_real_name(pkt['uniqname'])
            if self.last_seen_owners != None and person not in self.last_seen_owners:
                self.last_seen_rfids[person] = 1 #number of scans to remember their entry
                print("\n" + cur_datetime() + ": " + person + " has entered " + str(LOCATION) + "\n")
                #send to GATD
                print("Send things to GATD\n Send? thing just printed")
            self.update()


# looks for fitbit events periodically 
# i.e., does not require a door sensor
class PollingMonitor(Thread, FitbitMonitor):

    def __init__(self, interval_secs):
        # thread stuff
        super(PollingMonitor, self).__init__()
        self.daemon = True
        self.cancelled = False
        # logic parameters
        self.interval_secs = interval_secs
        # gooooooooo
        self.start()

    def run(self):
        while not self.cancelled:
            print("\nPolling {}".format(strftime("%Y-%m-%d %H:%M:%S")))
            self.update()
            sleep(self.interval_secs)

    def cancel(self):
        self.cancelled = True





#XXX: Fix this
#def main():
#    trackers = discover_fitbits()
#    if (trackers is None):
#        return
#    for [ID, RSSI] in trackers:
#        print("ID: " + str(ID) + " RSSI: " + str(RSSI))

if __name__ == "__main__":
    main()
