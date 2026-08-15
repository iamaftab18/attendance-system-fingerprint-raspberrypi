#!/usr/bin/env python3
"""
Interactive R307S fingerprint sensor test for Raspberry Pi.

Install on the Pi:
  python3 -m pip install pyfingerprint pyserial

Run:
  python3 scripts/r307s_test.py

Optional fixed port:
  FINGERPRINT_PORT=/dev/serial0 python3 scripts/r307s_test.py
"""

import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.r307s_sensor import connect_r307s


try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except Exception as exc:
    print(f'pyfingerprint is not installed or failed to import: {exc}')
    print('Install it on Raspberry Pi with: python3 -m pip install pyfingerprint pyserial')
    raise SystemExit(1)


def wait_for_finger(sensor, message):
    print(message, end='', flush=True)
    while True:
        try:
            if sensor.readImage():
                print(' image taken')
                return True
        except Exception as exc:
            print(f'\nSensor read failed: {exc}')
            return False
        print('.', end='', flush=True)
        time.sleep(0.15)


def wait_for_remove(sensor):
    print('Remove finger', end='', flush=True)
    while True:
        try:
            if not sensor.readImage():
                print(' done')
                return True
        except Exception as exc:
            print(f'\nSensor read failed while waiting for removal: {exc}')
            return False
        print('.', end='', flush=True)
        time.sleep(0.15)


def get_number(prompt='Enter ID from 1 to 127: '):
    while True:
        try:
            value = int(input(prompt).strip())
        except ValueError:
            print('Please enter a number.')
            continue
        if 1 <= value <= 127:
            return value
        print('ID must be between 1 and 127.')


def show_status(sensor, port):
    print('\n--- Sensor Status ---')
    print(f'Port: {port}')
    print(f'Template count: {sensor.getTemplateCount()}')
    print(f'Storage capacity: {sensor.getStorageCapacity()}')
    try:
        print(f'Security level: {sensor.getSecurityLevel()}')
    except Exception:
        pass
    print('---------------------')


def find_finger(sensor):
    if not wait_for_finger(sensor, 'Place finger on sensor'):
        return

    try:
        sensor.convertImage(0x01)
        position, accuracy = sensor.searchTemplate()
    except Exception as exc:
        print(f'Search failed: {exc}')
        return

    if position == -1:
        print('Finger not found.')
        return
    print(f'Detected template #{position} with confidence {accuracy}.')


def enroll_finger(sensor):
    location = get_number()

    if not wait_for_finger(sensor, 'Place finger on sensor'):
        return

    try:
        sensor.convertImage(0x01)
        position, _ = sensor.searchTemplate()
        if position >= 0:
            print(f'This finger is already enrolled at template #{position}.')
            return
    except Exception as exc:
        print(f'First scan failed: {exc}')
        return

    if not wait_for_remove(sensor):
        return

    if not wait_for_finger(sensor, 'Place the same finger again'):
        return

    try:
        sensor.convertImage(0x02)
        if sensor.compareCharacteristics() == 0:
            print('The two scans did not match.')
            return
        sensor.createTemplate()
        stored_at = sensor.storeTemplate(location)
    except Exception as exc:
        print(f'Enrollment failed: {exc}')
        return

    print(f'Fingerprint stored successfully at template #{stored_at}.')


def delete_finger(sensor):
    location = get_number('Enter template ID to delete from 1 to 127: ')
    try:
        sensor.deleteTemplate(location)
    except Exception as exc:
        print(f'Delete failed: {exc}')
        return
    print(f'Deleted template #{location}.')


def main():
    requested_port = os.environ.get('FINGERPRINT_PORT')
    print('Connecting to R307S fingerprint sensor...')
    sensor, port, diagnostics = connect_r307s(port=requested_port)
    if not sensor:
        print('\nSensor offline. Tried these ports:')
        for line in diagnostics:
            print(f'  - {line}')
        print('\nRaspberry Pi checklist:')
        print('  1. Connect sensor TX to Pi RX GPIO15, sensor RX to Pi TX GPIO14, GND to GND.')
        print('  2. Power the sensor with the correct voltage for your module, commonly 5V VCC with 3.3V UART logic.')
        print('  3. Enable serial port and disable serial console: sudo raspi-config')
        print('  4. Reboot, then check ports: ls -l /dev/serial0 /dev/ttyAMA0 /dev/ttyS0 /dev/ttyUSB0')
        print('  5. If using USB-TTL, run: FINGERPRINT_PORT=/dev/ttyUSB0 python3 scripts/r307s_test.py')
        raise SystemExit(1)

    for line in diagnostics:
        print(f'  {line}')
    show_status(sensor, port)

    while True:
        print('\n----------------')
        print('s) sensor status')
        print('e) enroll print')
        print('f) find print')
        print('d) delete print')
        print('q) quit')
        print('----------------')
        choice = input('> ').strip().lower()

        if choice == 's':
            show_status(sensor, port)
        elif choice == 'e':
            enroll_finger(sensor)
        elif choice == 'f':
            find_finger(sensor)
        elif choice == 'd':
            delete_finger(sensor)
        elif choice == 'q':
            break


if __name__ == '__main__':
    main()
