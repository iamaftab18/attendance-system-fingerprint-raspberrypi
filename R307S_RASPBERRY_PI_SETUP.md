# R307S Fingerprint Sensor on Raspberry Pi

## Install Python Packages

```bash
python3 -m pip install pyfingerprint pyserial
```

## Wiring

For direct Raspberry Pi UART wiring:

```text
R307S TX  -> Raspberry Pi RX GPIO15, physical pin 10
R307S RX  -> Raspberry Pi TX GPIO14, physical pin 8
R307S GND -> Raspberry Pi GND
R307S VCC -> Sensor module supported VCC, commonly 5V
```

Many R307S modules accept 5V power but use 3.3V UART logic. Check your exact module before wiring.

For USB-to-TTL adapter wiring, the sensor usually appears as `/dev/ttyUSB0`.

## Enable Raspberry Pi Serial Port

Run:

```bash
sudo raspi-config
```

Use:

```text
Interface Options -> Serial Port
Login shell over serial: No
Serial port hardware enabled: Yes
```

Then reboot:

```bash
sudo reboot
```

## Test The Sensor

From the project folder:

```bash
python3 scripts/r307s_test.py
```

If you know the exact port:

```bash
FINGERPRINT_PORT=/dev/serial0 python3 scripts/r307s_test.py
FINGERPRINT_PORT=/dev/ttyUSB0 python3 scripts/r307s_test.py
```

## Run The Flask App With A Fixed Port

```bash
FINGERPRINT_PORT=/dev/serial0 python3 app.py
```

The app now checks these ports automatically:

```text
/dev/serial0
/dev/ttyUSB0
/dev/ttyUSB1
/dev/ttyAMA0
/dev/ttyS0
/dev/serial/by-id/*
/dev/serial/by-path/*
```

Open `/fingerprint/status` in the browser to see which ports were tried.

## Camera Setup (Face Enrollment)

Face capture needs a USB webcam visible to OpenCV as a V4L2 device (not a CSI
ribbon camera - those need `libcamera`/`picamera2`, which this app doesn't use).

**1. Confirm the OS sees the webcam:**

```bash
ls /dev/video*
```

If nothing is listed, the webcam isn't detected at the OS level - check the
USB connection with `lsusb`, try a different port, and confirm `dmesg | tail`
shows it enumerating on plug-in. This is a hardware/driver issue no amount of
Python code can work around.

**2. If `/dev/video0` isn't the right index** (e.g. a second video device
exists, or only `/dev/video1` shows up), pin it explicitly:

```bash
CAMERA_INDEX=1 python3 app.py
```

**3. Make sure the app's user can access it:**

```bash
groups $USER   # must include "video"; if not:
sudo usermod -aG video $USER   # then log out/in (or reboot)
```

**4. Confirm OpenCV actually has its Haar cascade data files.** Some
piwheels/ARM builds of `opencv-contrib-python` install without them, which
crashes face detection even though the camera itself is fine:

```bash
python3 -c "import cv2; print(cv2.data.haarcascades)"
ls "$(python3 -c 'import cv2; print(cv2.data.haarcascades)')"
```

If `haarcascade_frontalface_default.xml` isn't in that listing, reinstall with
data files included:

```bash
pip install --force-reinstall --no-cache-dir opencv-contrib-python
```

or fall back to the system package, which the app will also search for
automatically (`/usr/share/opencv4/haarcascades/`):

```bash
sudo apt install -y libopencv-data
```

Once both the camera and the cascade files are confirmed, the Face
Enrollment button will open the camera, capture samples, and retrain the
model - check the server console for `[Camera]` / `[FaceRecognizer]` log
lines if it still fails.
