import glob
import os


DEFAULT_BAUDRATE = 57600
DEFAULT_ADDRESS = 0xFFFFFFFF
DEFAULT_PASSWORD = 0x00000000


def candidate_ports():
    """Return serial ports commonly used by R307S sensors on Raspberry Pi."""
    ports = []
    env_port = os.environ.get('FINGERPRINT_PORT')
    if env_port:
        ports.append(env_port)

    ports.extend([
        '/dev/serial0',
        '/dev/ttyUSB0',
        '/dev/ttyUSB1',
        '/dev/ttyAMA0',
        '/dev/ttyS0',
    ])
    ports.extend(sorted(glob.glob('/dev/serial/by-id/*')))
    ports.extend(sorted(glob.glob('/dev/serial/by-path/*')))

    unique_ports = []
    for port in ports:
        if port and port not in unique_ports:
            unique_ports.append(port)
    return unique_ports


def connect_r307s(port=None, baudrate=None, address=None, password=None):
    """Try to connect to an R307S-compatible fingerprint sensor."""
    baudrate = baudrate or int(os.environ.get('FINGERPRINT_BAUDRATE', DEFAULT_BAUDRATE))
    address = address if address is not None else DEFAULT_ADDRESS
    password = password if password is not None else DEFAULT_PASSWORD
    ports = [port] if port else candidate_ports()
    diagnostics = []

    try:
        from pyfingerprint.pyfingerprint import PyFingerprint
    except Exception as exc:
        return None, None, [f'pyfingerprint import failed: {exc}']

    for candidate in ports:
        if candidate.startswith('/dev/') and not os.path.exists(candidate):
            diagnostics.append(f'{candidate}: not found')
            continue

        try:
            sensor = PyFingerprint(candidate, baudrate, address, password)
            if not sensor.verifyPassword():
                diagnostics.append(f'{candidate}: sensor password verification failed')
                continue
            diagnostics.append(f'{candidate}: connected')
            return sensor, candidate, diagnostics
        except Exception as exc:
            diagnostics.append(f'{candidate}: {exc}')

    return None, None, diagnostics
