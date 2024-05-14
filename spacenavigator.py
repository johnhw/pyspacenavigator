from time import sleep
import pywinusb.hid as hid
from collections import namedtuple
import timeit
import copy
from pywinusb.hid import usage_pages, helpers, winapi

# current version number
__version__ = "0.2.3"

# clock for timing
high_acc_clock = timeit.default_timer


GENERIC_PAGE = 0x1
BUTTON_PAGE = 0x9
LED_PAGE = 0x8
MULTI_AXIS_CONTROLLER_CAP = 0x8

HID_AXIS_MAP = {
    0x30: "x",
    0x31: "y",
    0x32: "z",
    0x33: "roll",
    0x34: "pitch",
    0x35: "yaw",
}

import pprint

# axis mappings are specified as:
# [channel, byte1, byte2, scale]; scale is usually just -1 or 1 and multiplies the result by this value
# (but per-axis scaling can also be achieved by setting this value)
# byte1 and byte2 are indices into the HID array indicating the two bytes to read to form the value for this axis
# For the SpaceNavigator, these are consecutive bytes following the channel number.
AxisSpec = namedtuple("AxisSpec", ["channel", "byte1", "byte2", "scale"])


# button states are specified as:
# [channel, data byte,  bit of byte, index to write to]
# If a message is received on the specified channel, the value of the data byte is set in the button bit array
ButtonSpec = namedtuple("ButtonSpec", ["channel", "byte", "bit"])


## Simple HID code to read data from the 3dconnexion devices

# convert two 8 bit bytes to a signed 16 bit integer
def to_int16(y1, y2):
    x = (y1) | (y2 << 8)
    if x >= 32768:
        x = -(65536 - x)
    return x


# tuple for 6DOF results
SpaceNavigator = namedtuple(
    "SpaceNavigator", ["t", "x", "y", "z", "roll", "pitch", "yaw", "buttons"]
)


class ButtonState(list):
    def __int__(self):
        return sum((b << i) for (i, b) in enumerate(reversed(self)))


class DeviceSpec(object):
    """Holds the specification of a single 3Dconnexion device"""

    def __init__(
        self, name, hid_id, led_id, mappings, button_mapping, axis_scale=350.0
    ):
        self.name = name
        self.hid_id = hid_id
        self.led_id = led_id
        self.mappings = mappings
        self.button_mapping = button_mapping
        self.axis_scale = axis_scale

        self.led_usage = hid.get_full_usage_id(led_id[0], led_id[1])
        # initialise to a vector of 0s for each state
        self.dict_state = {
            "t": -1,
            "x": 0,
            "y": 0,
            "z": 0,
            "roll": 0,
            "pitch": 0,
            "yaw": 0,
            "buttons": ButtonState([0] * len(self.button_mapping)),
        }
        self.tuple_state = SpaceNavigator(**self.dict_state)

        # start in disconnected state
        self.device = None
        self.callback = None
        self.button_callback = None

    def describe_connection(self):
        """Return string representation of the device, including
        the connection state"""
        if self.device == None:
            return "%s [disconnected]" % (self.name)
        else:
            return "%s connected to %s %s version: %s [serial: %s]" % (
                self.name,
                self.vendor_name,
                self.product_name,
                self.version_number,
                self.serial_number,
            )

    @property
    def connected(self):
        """True if the device has been connected"""
        return self.device is not None

    @property
    def state(self):
        """Return the current value of read()

        Returns: state: {t,x,y,z,pitch,yaw,roll,button} namedtuple
                None if the device is not open.
        """
        return self.read()

    def open(self):
        """Open a connection to the device, if possible"""
        if self.device:
            self.device.open()
        # copy in product details
        self.product_name = self.device.product_name
        self.vendor_name = self.device.vendor_name
        self.version_number = self.device.version_number
        # doesn't seem to work on 3dconnexion devices...
        # serial number will be a byte string, we convert to a hex id
        self.serial_number = "".join(
            ["%02X" % ord(char) for char in self.device.serial_number]
        )

    def set_led(self, state):
        """Set the LED state to state (True or False)"""
        if self.connected:
            reports = self.device.find_output_reports()
            for report in reports:
                if self.led_usage in report:
                    report[self.led_usage] = state
                    report.send()

    def close(self):
        """Close the connection, if it is open"""
        if self.connected:
            self.device.close()
            self.device = None

    def read(self):
        """Return the current state of this navigation controller.

        Returns:
            state: {t,x,y,z,pitch,yaw,roll,button} namedtuple
            None if the device is not open.
        """
        if self.connected:
            return self.tuple_state
        else:
            return None

    def process(self, data):
        """
        Update the state based on the incoming data

        This function updates the state of the DeviceSpec object, giving values for each
        axis [x,y,z,roll,pitch,yaw] in range [-1.0, 1.0]
        The state tuple is only set when all 6 DoF have been read correctly.

        The timestamp (in fractional seconds since the start of the program)  is written as element "t"

        If callback is provided, it is called on with a copy of the current state tuple.
        If button_callback is provided, it is called only on button state changes with the argument (state, button_state).

        Parameters:
            data    The data for this HID event, as returned by the HID callback

        """
        button_changed = False

        for name, (chan, b1, b2, flip) in self.mappings.items():
            if data[0] == chan:
                self.dict_state[name] = (
                    flip * to_int16(data[b1], data[b2]) / float(self.axis_scale)
                )

        for button_index, (chan, byte, bit) in enumerate(self.button_mapping):
            if data[0] == chan:
                button_changed = True
                # update the button vector
                mask = 1 << bit
                self.dict_state["buttons"][button_index] = (
                    1 if (data[byte] & mask) != 0 else 0
                )

        self.dict_state["t"] = high_acc_clock()

        # must receive both parts of the 6DOF state before we return the state dictionary
        if len(self.dict_state) == 8:
            self.tuple_state = SpaceNavigator(**self.dict_state)

        # call any attached callbacks
        if self.callback:
            self.callback(self.tuple_state)

        # only call the button callback if the button state actually changed
        if self.button_callback and button_changed:
            self.button_callback(self.tuple_state, self.tuple_state.buttons)


# the IDs for the supported devices
# Each ID maps a device name to a DeviceSpec object
device_specs = {
    "SpaceNavigator": DeviceSpec(
        name="SpaceNavigator",
        # vendor ID and product ID
        hid_id=[0x46D, 0xC626],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=2, byte1=1, byte2=2, scale=-1),
            "roll": AxisSpec(channel=2, byte1=3, byte2=4, scale=-1),
            "yaw": AxisSpec(channel=2, byte1=5, byte2=6, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),
            ButtonSpec(channel=3, byte=1, bit=1),
        ],
        axis_scale=350.0,
    ),
    "SpaceMouse Compact": DeviceSpec(
        name="SpaceMouse Compact",
        # vendor ID and product ID
        hid_id=[0x256F, 0xC635],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=2, byte1=1, byte2=2, scale=-1),
            "roll": AxisSpec(channel=2, byte1=3, byte2=4, scale=-1),
            "yaw": AxisSpec(channel=2, byte1=5, byte2=6, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),
            ButtonSpec(channel=3, byte=1, bit=1),
        ],
        axis_scale=350.0,
    ),    
    "SpaceMouse Pro Wireless": DeviceSpec(
        name="SpaceMouse Pro Wireless",
        # vendor ID and product ID
        hid_id=[0x256F, 0xC632],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=1, byte1=7, byte2=8, scale=-1),
            "roll": AxisSpec(channel=1, byte1=9, byte2=10, scale=-1),
            "yaw": AxisSpec(channel=1, byte1=11, byte2=12, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),  # MENU
            ButtonSpec(channel=3, byte=3, bit=7),  # ALT
            ButtonSpec(channel=3, byte=4, bit=1),  # CTRL
            ButtonSpec(channel=3, byte=4, bit=0),  # SHIFT
            ButtonSpec(channel=3, byte=3, bit=6),  # ESC
            ButtonSpec(channel=3, byte=2, bit=4),  # 1
            ButtonSpec(channel=3, byte=2, bit=5),  # 2
            ButtonSpec(channel=3, byte=2, bit=6),  # 3
            ButtonSpec(channel=3, byte=2, bit=7),  # 4
            ButtonSpec(channel=3, byte=2, bit=0),  # ROLL CLOCKWISE
            ButtonSpec(channel=3, byte=1, bit=2),  # TOP
            ButtonSpec(channel=3, byte=4, bit=2),  # ROTATION
            ButtonSpec(channel=3, byte=1, bit=5),  # FRONT
            ButtonSpec(channel=3, byte=1, bit=4),  # REAR
            ButtonSpec(channel=3, byte=1, bit=1),
        ],  # FIT
        axis_scale=350.0,
    ),
    # identical, but with 0xc631 device ID
    "SpaceMouse Pro Wireless": DeviceSpec(
        name="SpaceMouse Pro Wireless",
        # vendor ID and product ID
        hid_id=[0x256F, 0xC631],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=1, byte1=7, byte2=8, scale=-1),
            "roll": AxisSpec(channel=1, byte1=9, byte2=10, scale=-1),
            "yaw": AxisSpec(channel=1, byte1=11, byte2=12, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),  # MENU
            ButtonSpec(channel=3, byte=3, bit=7),  # ALT
            ButtonSpec(channel=3, byte=4, bit=1),  # CTRL
            ButtonSpec(channel=3, byte=4, bit=0),  # SHIFT
            ButtonSpec(channel=3, byte=3, bit=6),  # ESC
            ButtonSpec(channel=3, byte=2, bit=4),  # 1
            ButtonSpec(channel=3, byte=2, bit=5),  # 2
            ButtonSpec(channel=3, byte=2, bit=6),  # 3
            ButtonSpec(channel=3, byte=2, bit=7),  # 4
            ButtonSpec(channel=3, byte=2, bit=0),  # ROLL CLOCKWISE
            ButtonSpec(channel=3, byte=1, bit=2),  # TOP
            ButtonSpec(channel=3, byte=4, bit=2),  # ROTATION
            ButtonSpec(channel=3, byte=1, bit=5),  # FRONT
            ButtonSpec(channel=3, byte=1, bit=4),  # REAR
            ButtonSpec(channel=3, byte=1, bit=1),
        ],  # FIT
        axis_scale=350.0,
    ),
    "SpaceMouse Pro": DeviceSpec(
        name="SpaceMouse Pro",
        # vendor ID and product ID
        hid_id=[0x46D, 0xC62b],
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=2, byte1=1, byte2=2, scale=-1),
            "roll": AxisSpec(channel=2, byte1=3, byte2=4, scale=-1),
            "yaw": AxisSpec(channel=2, byte1=5, byte2=6, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),  # MENU
            ButtonSpec(channel=3, byte=3, bit=7),  # ALT
            ButtonSpec(channel=3, byte=4, bit=1),  # CTRL
            ButtonSpec(channel=3, byte=4, bit=0),  # SHIFT
            ButtonSpec(channel=3, byte=3, bit=6),  # ESC
            ButtonSpec(channel=3, byte=2, bit=4),  # 1
            ButtonSpec(channel=3, byte=2, bit=5),  # 2
            ButtonSpec(channel=3, byte=2, bit=6),  # 3
            ButtonSpec(channel=3, byte=2, bit=7),  # 4
            ButtonSpec(channel=3, byte=2, bit=0),  # ROLL CLOCKWISE
            ButtonSpec(channel=3, byte=1, bit=2),  # TOP
            ButtonSpec(channel=3, byte=4, bit=2),  # ROTATION
            ButtonSpec(channel=3, byte=1, bit=5),  # FRONT
            ButtonSpec(channel=3, byte=1, bit=4),  # REAR
            ButtonSpec(channel=3, byte=1, bit=1),  # FIT
        ],  
        axis_scale=350.0,
    ),
    "SpaceMouse Wireless": DeviceSpec(
        name="SpaceMouse Wireless",
        # vendor ID and product ID
        hid_id=[0x256F, 0xC62E],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=1, byte1=7, byte2=8, scale=-1),
            "roll": AxisSpec(channel=1, byte1=9, byte2=10, scale=-1),
            "yaw": AxisSpec(channel=1, byte1=11, byte2=12, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0), #LEFT
            ButtonSpec(channel=3, byte=1, bit=1), #RIGHT
        ],  # FIT
        axis_scale=350.0,
    ),
    "3Dconnexion Universal Receiver": DeviceSpec(
        name="3Dconnexion Universal Receiver",
        # vendor ID and product ID
        hid_id=[0x256F, 0xC652],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=1, byte1=7, byte2=8, scale=-1),
            "roll": AxisSpec(channel=1, byte1=9, byte2=10, scale=-1),
            "yaw": AxisSpec(channel=1, byte1=11, byte2=12, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=1, bit=0),  # MENU
            ButtonSpec(channel=3, byte=3, bit=7),  # ALT
            ButtonSpec(channel=3, byte=4, bit=1),  # CTRL
            ButtonSpec(channel=3, byte=4, bit=0),  # SHIFT
            ButtonSpec(channel=3, byte=3, bit=6),  # ESC
            ButtonSpec(channel=3, byte=2, bit=4),  # 1
            ButtonSpec(channel=3, byte=2, bit=5),  # 2
            ButtonSpec(channel=3, byte=2, bit=6),  # 3
            ButtonSpec(channel=3, byte=2, bit=7),  # 4
            ButtonSpec(channel=3, byte=2, bit=0),  # ROLL CLOCKWISE
            ButtonSpec(channel=3, byte=1, bit=2),  # TOP
            ButtonSpec(channel=3, byte=4, bit=2),  # ROTATION
            ButtonSpec(channel=3, byte=1, bit=5),  # FRONT
            ButtonSpec(channel=3, byte=1, bit=4),  # REAR
            ButtonSpec(channel=3, byte=1, bit=1),
        ],  # FIT
        axis_scale=350.0,
    ),
    "SpacePilot Pro": DeviceSpec(
        name="SpacePilot Pro",
        # vendor ID and product ID
        hid_id=[0x46D, 0xC629],
        # LED HID usage code pair
        led_id=[0x8, 0x4B],
        mappings={
            "x": AxisSpec(channel=1, byte1=1, byte2=2, scale=1),
            "y": AxisSpec(channel=1, byte1=3, byte2=4, scale=-1),
            "z": AxisSpec(channel=1, byte1=5, byte2=6, scale=-1),
            "pitch": AxisSpec(channel=2, byte1=1, byte2=2, scale=-1),
            "roll": AxisSpec(channel=2, byte1=3, byte2=4, scale=-1),
            "yaw": AxisSpec(channel=2, byte1=5, byte2=6, scale=1),
        },
        button_mapping=[
            ButtonSpec(channel=3, byte=4, bit=0),  # SHIFT
            ButtonSpec(channel=3, byte=3, bit=6),  # ESC
            ButtonSpec(channel=3, byte=4, bit=1),  # CTRL
            ButtonSpec(channel=3, byte=3, bit=7),  # ALT
            ButtonSpec(channel=3, byte=3, bit=1),  # 1
            ButtonSpec(channel=3, byte=3, bit=2),  # 2
            ButtonSpec(channel=3, byte=2, bit=6),  # 3
            ButtonSpec(channel=3, byte=2, bit=7),  # 4
            ButtonSpec(channel=3, byte=3, bit=0),  # 5
            ButtonSpec(channel=3, byte=1, bit=0),  # MENU
            ButtonSpec(channel=3, byte=4, bit=6),  # -
            ButtonSpec(channel=3, byte=4, bit=5),  # +
            ButtonSpec(channel=3, byte=4, bit=4),  # DOMINANT
            ButtonSpec(channel=3, byte=4, bit=3),  # PAN/ZOOM
            ButtonSpec(channel=3, byte=4, bit=2),  # ROTATION
            ButtonSpec(channel=3, byte=2, bit=0),  # ROLL CLOCKWISE
            ButtonSpec(channel=3, byte=1, bit=2),  # TOP
            ButtonSpec(channel=3, byte=1, bit=5),  # FRONT
            ButtonSpec(channel=3, byte=1, bit=4),  # REAR
            ButtonSpec(channel=3, byte=2, bit=2),  # ISO
            ButtonSpec(channel=3, byte=1, bit=1),  # FIT
        ], 
        axis_scale=350.0,
    ),
}


# [For the SpaceNavigator]
# The HID data is in the format
# [id, a, b, c, d, e, f]
# each pair (a,b), (c,d), (e,f) is a 16 bit signed value representing the absolute device state [from -350 to 350]

# if id==1, then the mapping is
# (a,b) = y translation
# (c,d) = x translation
# (e,f) = z translation

# if id==2 then the mapping is
# (a,b) = x tilting (roll)
# (c,d) = y tilting (pitch)
# (d,e) = z tilting (yaw)

# if id==3 then the mapping is
# a = button. Bit 1 = button 1, bit 2 = button 2

# Each movement of the device always causes two HID events, one
# with id 1 and one with id 2, to be generated, one after the other.


supported_devices = list(device_specs.keys())
_active_device = None


def close():
    """Close the active device, if it exists"""
    if _active_device is not None:
        _active_device.close()


def read():
    """Return the current state of the active navigation controller.

    Returns:
        state: {t,x,y,z,pitch,yaw,roll,button} namedtuple
        None if the device is not open.
    """
    if _active_device is not None:
        return _active_device.tuple_state
    else:
        return None


def list_devices():
    """Return a list of the supported devices connected

    Returns:
        A list of string names of the devices supported which were found. Empty if no supported devices found
    """
    devices = []
    all_hids = hid.find_all_hid_devices()
    if all_hids:
        for index, device in enumerate(all_hids):
            for device_name, spec in device_specs.items():
                if (
                    device.vendor_id == spec.hid_id[0]
                    and device.product_id == spec.hid_id[1]
                ):
                    devices.append(device_name)
    return devices


def open(callback=None, button_callback=None, device=None, DeviceNumber=0):
    """
    Open a 3D space navigator device. Makes this device the current active device, which enables the module-level read() and close()
    calls. For multiple devices, use the read() and close() calls on the returned object instead, and don't use the module-level calls.

    Parameters:
        callback: If callback is provided, it is called on each HID update with a copy of the current state namedtuple
        button_callback: If button_callback is provided, it is called on each button push, with the arguments (state_tuple, button_state)
        device: name of device to open. Must be one of the values in supported_devices. If None, chooses the first supported device found.
        DeviceNumber: use the first (DeviceNumber=0) device you find. (for universal wireless receiver)
    Returns:
        Device object if the device was opened successfully
        None if the device could not be opened
    """
    # only used if the module-level functions are used
    global _active_device

    # if no device name specified, look for any matching device and choose the first
    if device == None:
        all_devices = list_devices()
        if len(all_devices) > 0:
            device = all_devices[0]
        else:
            return None

    found_devices = []
    all_hids = hid.find_all_hid_devices()
    if all_hids:
        for index, dev in enumerate(all_hids):
            spec = device_specs[device]
            if dev.vendor_id == spec.hid_id[0] and dev.product_id == spec.hid_id[1]:
                found_devices.append({"Spec":spec,"HIDDevice":dev})
                print("%s found" % device)

    else:
        print("No HID devices detected")
        return None


    if len(found_devices) == 0:
        print("No supported devices found")
        return None
    else:
        
        if len(found_devices) <= DeviceNumber:
            DeviceNumber = 0

        if len(found_devices) > DeviceNumber:
            # create a copy of the device specification
            spec = found_devices[DeviceNumber]["Spec"]
            dev = found_devices[DeviceNumber]["HIDDevice"]
            new_device = copy.deepcopy(spec)
            new_device.device = dev

            # set the callbacks
            new_device.callback = callback
            new_device.button_callback = button_callback
            # open the device and set the data handler
            new_device.open()
            dev.set_raw_data_handler(lambda x: new_device.process(x))
            _active_device = new_device
            return new_device

    print("Unknown error occured.")
    return None


def print_state(state):
    # simple default printer callback
    if state:
        print(
            " ".join(
                [
                    "%4s %+.2f" % (k, getattr(state, k))
                    for k in ["x", "y", "z", "roll", "pitch", "yaw", "t"]
                ]
            )
        )


def toggle_led(state, buttons):
    print("".join(["buttons=", str(buttons)]))
    # Switch on the led on left push, off on right push
    if buttons[0] == 1:
        set_led(1)
    if buttons[1] == 1:
        set_led(0)


def set_led(state):
    if _active_device:
        _active_device.set_led(state)


if __name__ == "__main__":
    print("Devices found:\n\t%s" % "\n\t".join(list_devices()))
    dev = open(callback=print_state, button_callback=toggle_led)
    print(dev.describe_connection())

    if dev:
        dev.set_led(0)
        while 1:
            sleep(1)
            dev.set_led(1)
            sleep(1)
            dev.set_led(0)

            
