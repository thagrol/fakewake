#!/usr/bin/env python

## simple script to monitor a gpio pin with attached button
## and shutdown pi when pressed for > 2 seconds
## must be run as root or via sudo

# imports
from gpiozero import Button
from os import system
from time import sleep

# config
PIN = 17
PULL_UP = True
HOLD_TIME = 2

# functions
def btn_held():
    # respond to long press on button
    system("poweroff")

# do stuff
if __name__ == '__main__':
    pbutton = Button(pin=PIN,
                     pull_up=PULL_UP,
                     hold_time=HOLD_TIME,
                     hold_repeat=False)
    pbutton.when_held = btn_held

    while True:
       sleep(1)
