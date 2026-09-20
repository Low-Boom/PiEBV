#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Control script for the Raspberry Pi Pico 2 W-based PiDG delay generator.

This is the Pico-protocol counterpart to "Chris Teensy Version/EBIV_Pulser_serial_py.txt":
same pyserial-based port-scanning approach, but talking the new line-based
ASCII protocol (see src/protocol.cpp) instead of the Teensy's
SimpleSerialShell/semicolon-terminated commands.

required package(s): pyserial
python -m pip install pyserial
"""
import glob
import platform
import sys
import time

import serial
from serial import SerialException

BAUDRATE = 115200


def open_port(baudrate=BAUDRATE, port=''):
    """
    Scan available serial ports for the Pico delay generator.
    port --> try only this port if given
    """
    ports = []
    if port != '':
        ports = [port]
    elif platform.system() == 'Darwin':  # macOS
        ports.extend(glob.glob('/dev/cu.usbmodem*'))
    elif platform.system() == 'Linux':
        ports.extend(glob.glob('/dev/ttyACM*'))
    elif platform.system() == 'Windows':
        ports.extend(['COM%d' % i for i in range(1, 33)])
    else:
        raise Exception('Cannot determine host system! Found: ' + platform.system())

    for candidate in ports:
        try:
            pico_port = serial.Serial(port=candidate, baudrate=baudrate, timeout=1)
        except SerialException:
            continue  # try next

        print('Checking port ' + candidate)
        pico_port.write(b'ID?\n')
        time.sleep(0.1)
        reply = pico_port.read(10000)
        try:
            reply_str = reply.decode('utf-8')
        except UnicodeDecodeError:
            pico_port.close()
            continue

        if 'PiDG' in reply_str:
            print(reply_str)
            print('Communication successfully started on port ' + candidate)
            return pico_port, candidate
        pico_port.close()

    print('Problem opening serial connection to device\n   Quitting...')
    return None, 'None'


def write_read(port, command):
    """Send one command line and return the decoded response."""
    port.write((command.strip() + '\n').encode('utf-8'))
    time.sleep(0.05)
    return port.read(10000).decode('utf-8', errors='replace')


if __name__ == '__main__':
    pico, com_port = open_port(baudrate=BAUDRATE)
    if pico is None:
        sys.exit(-1)

    print("Type a command (e.g. 'FREQ 1000', 'WIDTH', 'STATUS', 'HELP'), or 'x' to exit.")
    while True:
        val = input('Enter a command ("x" to exit): ')
        if val == 'x':
            break
        print('Sending: ' + val)
        response = write_read(pico, val)
        for line in response.splitlines():
            print(line)

    # Important: always close the port when done!
    pico.close()
