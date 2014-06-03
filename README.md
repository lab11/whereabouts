whereabouts
===========

Semantic heuristic localization

Requires:
 * fitbit wireless sync dongle
 * people wearing fitbits

All fitbits need to be identified so people and fitbit IDs can be correlated
data is stored to and pulled from [GATD](https://github.com/lab11/gatd)


## Fitbitfinder Installation steps
1. Install galileo, a python utility for interacting with fitbits
    `sudo pip install galileo`
2. Modify usb permissions
    `sudo cp 99-fitbit.rules /etc/udev/rules.d/99-fitbit.rules`
3. Run fitbitfinder
    `./fitbitfinder`


## Whereabouts Installation steps
1. Create a virtual environment
    `sudo pip install virtualenv`
    `virtualenv venv`
2. Start the virtual environment
    `source venv/bin/activate`
3. Install IPy and socketIO-client to virtual environment
    `pip install IPy`
    `pip install socketIO-client`
4. Replace init file from socketIO-client
    `cp socketIO_client__init__.py venv/lib/python2.7/site-packages/socketIO_client/__init__.py`
5. Run whereabouts
    `./wherabouts`

