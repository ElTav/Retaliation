#!/usr/bin/python
#
# Copyright 2011 PaperCut Software Int. Pty. Ltd. http://www.papercut.com/
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
# 

############################################################################
# 
# RETALIATION - A Teamcity "Extreme Feedback" Contraption
#
#    Lava Lamps are for pussies! Retaliate to a broken build with a barrage 
#    of foam missiles.
#
# Steps to use:
#
#  1.  Mount your Dream Cheeky Thunder USB missile launcher in a central and 
#      fixed location.
#
#  2.  Copy this script onto the system connected to your missile lanucher.
#
#  3.  Modify your `COMMAND_SETS` in the `retaliation.py` script to define 
#      your targeting commands for each one of your build-braking coders 
#      (their user ID as listed in Teamcity).  A command set is an array of 
#      move and fire commands. It is recommend to start each command set 
#      with a "zero" command.  This parks the launcher in a known position 
#      (bottom-left).  You can then use "up" and "right" followed by a 
#      time (in milliseconds) to position your fire.
# 
#      You can test a set by calling retaliation.py with the target name. 
#      e.g.:  
#
#           retaliation.py "[developer's user name]"
#
#      Trial and error is the best approch. Consider doing this secretly 
#      after hours for best results!
#
#  4.  Setup the Teamcity "notification" plugin. Define a UDP endpoint 
#      on port 22222 pointing to the system hosting this script.
#      Tip: Make sure your firewall is not blocking UDP on this port.
#
#  5.  Start listening for failed build events by running the command:
#          retaliation.py stalk
#      (Consider setting this up as a boot/startup script. On Windows 
#      start with pythonw.exe to keep it running hidden in the 
#      background.)
#
#  6.  Wait for DEFCON 1 - Let the war games begin!
#
#
#  Requirements:
#   * A Dream Cheeky Thunder USB Missile Launcher
#   * Python 2.6+
#   * Python PyUSB Support and its dependencies 
#      http://sourceforge.net/apps/trac/pyusb/
#      (on Mac use brew to "brew install libusb")
#   * Should work on Windows, Mac and Linux
#
#  Author:  Chris Dance <chris.dance@papercut.com>
#  Version: 1.0 : 2011-08-15
#
############################################################################

import sys
import platform
import time
import socket
import re
import json
import urllib2
import base64

import usb.core
import usb.util

##########################  CONFIG   #########################

#
# Define a dictionary of "command sets" that map usernames to a sequence 
# of commands to target the user (e.g their desk/workstation).  It's 
# suggested that each set start and end with a "zero" command so it's
# always parked in a known reference location. The timing on move commands
# is milli-seconds. The number after "fire" denotes the number of rockets
# to shoot.
#

# for the first launcher
COMMAND_SETS1 = {
    "wuhqureshi" : (
        ("zero", 0), # Zero/Park to know point (bottom-left)
        ("led", 1), # Turn the LED on
        ("right", 3250),
        ("up", 240),
        ("fire", 4), # Fire a full barrage of 4 missiles
        ("led", 0), # Turn the LED back off
        ("zero", 0), # Park after use for next time
    ),
	"paul.ness" : (
        ("zero", 0), # Zero/Park to know point (bottom-left)
        ("led", 1), # Turn the LED on
        ("right", 3250),
		("zero", 0),
		("right", 1850),
        ("up", 140),
        ("fire", 4), # Fire a full barrage of 4 missiles
        ("led", 0), # Turn the LED back off
        ("zero", 0), # Park after use for next time
    ),
    "tom" : (
        ("zero", 0), 
        ("right", 4400),
        ("up", 200),
        ("fire", 4),
        ("zero", 0),
    ),
    "phil" : (      # That's me - just dance around and missfire!
        ("zero", 0),
        ("right", 5200),
        ("up", 500),
        ("pause", 5000),
        ("left", 2200),
        ("down", 500),
        ("fire", 1),
        ("zero", 0),
    ),
}
# for the second launcher
COMMAND_SETS2 = {
    "leandro" : (
        ("zero", 0), 
        ("led", 1), 
        ("right", 3250),
        ("up", 300),
        ("fire", 3), 
        ("led", 0), 
        ("zero", 0), 
    ),
}


#
# The UDP port to listen to Teamcity events on (events are generated/supplied 
# by Teamcity "notification" plugin)
#
TEAMCITY_NOTIFICATION_UDP_PORT   = 22222

#
# The URL of your Teamcity server - used to callback to determine who broke 
# the build.
#
TEAMCITY_SERVER                  = "http://teamcity.haymarketmedia.com:7162"

#
# If you're Teamcity server is secured by HTTP basic auth, sent the
# username and password here.  Else leave this blank.
HTTPAUTH_USER                   = "XXX"
HTTPAUTH_PASS                   = "XXX"

##########################  ENG CONFIG  #########################

# The code...

# Protocol command bytes
DOWN    = 0x01
UP      = 0x02
LEFT    = 0x04
RIGHT   = 0x08
FIRE    = 0x10
STOP    = 0x20

DEVICE = None
DEVICE_TYPE = None

def usage():
    print "Usage: retaliation.py [command] [value]"
    print ""
    print "   commands:"
    print "     stalk - sit around waiting for a Teamcity CI failed build"
    print "             notification, then attack the perpetrator!"
    print ""
    print "     up    - move up <value> milliseconds"
    print "     down  - move down <value> milliseconds"
    print "     right - move right <value> milliseconds"
    print "     left  - move left <value> milliseconds"
    print "     fire  - fire <value> times (between 1-4)"
    print "     zero  - park at zero position (bottom-left)"
    print "     pause - pause <value> milliseconds"
    print "     led   - turn the led on or of (1 or 0)"
    print ""
    print "     <command_set_name> - run/test a defined COMMAND_SET"
    print "             e.g. run:"
    print "                  retaliation.py 'chris'"
    print "             to test targeting of chris as defined in your command set."
    print ""


def setup_usb():
    # Tested only with the Cheeky Dream Thunder
    # and original USB Launcher
    global DEVICE1
    global DEVICE2
 
    global DEVICE_TYPE

    #DEVICE1 = usb.core.find(idVendor=0x2123, idProduct=0x1010)
    #DEVICE2 = usb.core.find(idVendor=0x2123, idProduct=0x1010)
    DEVICES = usb.core.find(find_all=True,idVendor=0x2123, idProduct=0x1010)
    i = iter(DEVICES)

    DEVICE1 = i.next()
    DEVICE2 = i.next()


    if DEVICE1 is None or DEVICE2 is None:
	DEVICES = usb.core.find(find_all=True,idVendor=0x0a81, idProduct=0x0701)
    	i = iter(DEVICES)

	DEVICE1 = i.next()
	DEVICE2 = i.next()


        if DEVICE1 is None:
            raise ValueError('Missile device not found')
	if DEVICE2 is None:
            raise ValueError('Missile device not found')
        else:
            DEVICE_TYPE = "Original"
    else:
        DEVICE_TYPE = "Thunder"

    

    # On Linux we need to detach usb HID first
    if "Linux" == platform.system():
        try:
            DEVICE1.detach_kernel_driver(0)
            DEVICE2.detach_kernel_driver(0)

        except Exception, e:
            pass # already unregistered    

    DEVICE1.set_configuration()
    DEVICE2.set_configuration()



def send_cmd(cmd, device):
    if "Thunder" == DEVICE_TYPE:
	if device == 1:
		DEVICE1.ctrl_transfer(0x21, 0x09, 0, 0, [0x02, cmd, 0x00,0x00,0x00,0x00,0x00,0x00])
	elif device == 2:
		DEVICE2.ctrl_transfer(0x21, 0x09, 0, 0, [0x02, cmd, 0x00,0x00,0x00,0x00,0x00,0x00])

    elif "Original" == DEVICE_TYPE:
        if device == 1:
		DEVICE1.ctrl_transfer(0x21, 0x09, 0x0200, 0, [cmd])
	elif device == 2:
		DEVICE2.ctrl_transfer(0x21, 0x09, 0x0200, 0, [cmd])


def led(cmd, device):
    if "Thunder" == DEVICE_TYPE:
	if device == 1:
        	DEVICE1.ctrl_transfer(0x21, 0x09, 0, 0, [0x03, cmd, 0x00,0x00,0x00,0x00,0x00,0x00])
	elif device == 2:
        	DEVICE2.ctrl_transfer(0x21, 0x09, 0, 0, [0x03, cmd, 0x00,0x00,0x00,0x00,0x00,0x00])

    elif "Original" == DEVICE_TYPE:
        print("There is no LED on this device")

def send_move(cmd, duration_ms, device):
    send_cmd(cmd, device)
    time.sleep(duration_ms / 1000.0)
    send_cmd(STOP, device)


def run_command(command, value, dev):
    command = command.lower()
    if command == "right":
        send_move(RIGHT, value, dev)
    elif command == "left":
        send_move(LEFT, value, dev)
    elif command == "up":
        send_move(UP, value, dev)
    elif command == "down":
        send_move(DOWN, value, dev)
    elif command == "zero" or command == "park" or command == "reset":
        # Move to bottom-left
        send_move(DOWN, 2000, dev)
        send_move(LEFT, 8000, dev)
    elif command == "pause" or command == "sleep":
        time.sleep(value / 1000.0)
    elif command == "led":
        if value == 0:
            led(0x00, dev)
        else:
            led(0x01, dev)
    elif command == "fire" or command == "shoot":
        if value < 1 or value > 4:
            value = 1
        # Stabilize prior to the shot, then allow for reload time after.
        time.sleep(0.5)
        for i in range(value):
            send_cmd(FIRE, dev)
            time.sleep(4.5)
    else:
        print "Error: Unknown command: '%s'" % command


def run_command_set(commands, dev):
    for cmd, value in commands:
        run_command(cmd, value, dev)


def teamcity_target_user(user):
	
    match = False
    # Not efficient but our user list is probably less than 1k.
    # Do a case insenstive search for convenience.
    for key in COMMAND_SETS1:
        if key.lower() == user.lower():
            # We have a command set that targets our user so got for it!
            run_command_set(COMMAND_SETS[key], 1)
            match = True
            break
	for key in COMMAND_SETS2:
		if key.lower() == user.lower():
			# We have a command set that targets our user so got for it!
			run_command_set(COMMAND_SETS[key], 2)
			match = True
			break
    if not match:
        print "WARNING: No target command set defined for user %s" % user
	if match:
		print "Toast"


def read_url(url):
    request = urllib2.Request(url)

    if HTTPAUTH_USER and HTTPAUTH_PASS:
        authstring = base64.encodestring('%s:%s' % (HTTPAUTH_USER, HTTPAUTH_PASS))
        authstring = authstring.replace('\n', '')
        request.add_header("Authorization", "Basic %s" % authstring)
        request.add_header("Accept", "application/json, text/javascript")
        
    return urllib2.urlopen(request).read()


def teamcity_get_responsible_user():
    # Call back to Teamcity and determin who broke the build. (Hacky)
    # We do this by crudly parsing the changes on the last failed build
    
    changes_url = TEAMCITY_SERVER + "/httpAuth/app/rest/builds/running:false,status:failure"
    changedata = read_url(changes_url)
   
    # Look for the /user/[name] link
    m = re.compile('"username":"([^/"]+)').search(changedata)
    if m:
        print "Target identified '%s'" % m.group(1)
        return m.group(1)
    else:
        return None
		
def teamcity_get_broken_build_info():
    # Call back to Teamcity and determin who broke the build. (Hacky)
    # We do this by crudly parsing the changes on the last failed build
    
    changes_url = TEAMCITY_SERVER + "/httpAuth/app/rest/builds/running:false,status:failure"
    changedata = read_url(changes_url)
   
    # Look for the /user/[name] link
    m = re.compile('"projectName":"([^/"]+)').search(changedata)
    if m:
        return m.group(1)
    else:
        return None


def teamcity_wait_for_event():

    # Data in the format: 
    #   {"name":"Project", "url":"JobUrl", "build":{"number":1, "phase":"STARTED", "status":"FAILURE" }}
	try:
		while True:
			target = teamcity_get_responsible_user()
			build = teamcity_get_broken_build_info()
			if target == None:
				print "WARNING: Could not identify the user who broke the build!"
				continue

			print "Build Failed! Broken project is: " + build
			print "Build Failed! Targeting user: " + target			
			teamcity_target_user(target)
			time.sleep(60)
	except KeyboardInterrupt:
		pass
			
                

def main(args):

    if len(args) < 2:
        usage()
        sys.exit(1)

    setup_usb()

    if args[1] == "stalk":
        print "Listening and waiting for Teamcity failed build events..."
        teamcity_wait_for_event()
        #teamcity_get_responsible_user()
        # Will never return
        return
    command = args[1]

    if command in COMMAND_SETS1:
        run_command_set(COMMAND_SETS1[command], 1)
    if command in COMMAND_SETS2:
        run_command_set(COMMAND_SETS2[command], 2)

    # Process any passed commands or command_sets
    command = args[2]
    value = 0
    device = args[1]
    if len(args) > 2:
        value = int(args[3])


    else:
        run_command(command, value, int(dev))


if __name__ == '__main__':
    main(sys.argv)
