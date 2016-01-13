from time import sleep
import pywinusb.hid as hid
from collections import namedtuple
import timeit
import copy

# current version number
__version__=  "0.1.5"

# clock for timing
high_acc_clock = timeit.default_timer

## Simple HID code to read data from the 3dconnexion devices

# convert two 8 bit bytes to a signed 16 bit integer
def to_int16(y1,y2):
    x = (y1) | (y2<<8)
    if x>=32768:
        x = -(65536-x)
    return x

# tuple for 6DOF results
SpaceNavigator = namedtuple('SpaceNavigator', ['t','x', 'y', 'z', 'roll', 'pitch', 'yaw', 'button'])

class DeviceSpec(object):
    """Holds the specification of a single 3Dconnexion device"""
    def __init__(self, name, hid_id, led_id, mappings, button_mapping, axis_scale=350.0):
        self.name = name
        self.hid_id = hid_id
        self.led_id = led_id
        self.mappings = mappings
        self.button_mapping = button_mapping
        self.axis_scale = axis_scale        
        self.dict_state = {"button":0}
        self.tuple_state = SpaceNavigator(-1,0,0,0,0,0,0,0)
        # start in disconnected state
        self.device = None
        self.led_usage = hid.get_full_usage_id(self.led_id[0], self.led_id[1])
        self.callback = None
        self.button_callback = None
       
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
        The HID data is in the format
        [id, a, b, c, d, e, f]
        each pair (a,b), (c,d), (e,f) is a 16 bit signed value representing the absolute device state [from -350 to 350]
        
        if id==1, then the mapping is
        (a,b) = y translation
        (c,d) = x translation
        (e,f) = z translation
        
        if id==2 then the mapping is
        (a,b) = x tilting (roll)
        (c,d) = y tilting (pitch)
        (d,e) = z tilting (yaw)
        
        if id==3 then the mapping is
        a = button. Bit 1 = button 1, bit 2 = button 2
        
        Each movement of the device always causes two HID events, one
        with id 1 and one with id 2, to be generated, one after the other.
        
        This function updates the global state _space_navigator_dict, giving values for each
        axis [x,y,z,roll,pitch,yaw] in range [-1.0, 1.0]
        
        The timestamp (in fractional seconds since the start of the program)  is written as element "t"
        
        If callback is provided, it is called on with a copy of the current state tuple.
        If button_callback is provided, it is called only on button state changes with the argument (state, button_state).
        """
        
        button_pushed = False        
    
        for name,(chan,b1,b2,flip) in self.mappings.iteritems():
            if data[0] == chan:
                self.dict_state[name] = flip * to_int16(data[b1], data[b2])/float(self.axis_scale)
                
        for chan, byte, shift in self.button_mapping:
            if data[0] == chan:
                button_pushed = True               
                old_state = self.dict_state["button"]
                # clear the relevant byte of old_state and set the new state in that space
                old_state = old_state & ~((0xff)<<shift)
                self.dict_state["button"] = old_state | (data[byte] << shift)
                                        
        self.dict_state["t"] = high_acc_clock()
        
        # must receive both parts of the 6DOF state before we return the state dictionary
        if len(self.dict_state)==8:
            self.tuple_state = SpaceNavigator(**self.dict_state)
        
        # call any attached callbacks
        if self.callback:
            self.callback(self.tuple_state)                        
        
        if self.button_callback and button_pushed:            
            self.button_callback(self.tuple_state, self.tuple_state.button)
                      
   
# the ID for the space navigator        
device_specs = {
    "SpaceNavigator":   DeviceSpec(name="SpaceNavigator", 
                        hid_id=[0x46d, 0xc626], 
                        led_id=[0x8, 0x4b],
    
                        # axis mappings are specified as:
                        # [channel, byte1, byte2, scale]; scale is usually just -1 or 1 and multiplies the result by this value 
                        # byte1 and byte2 are indices into the HID array indicating the two bytes to read to form the value for this axis
                        # For the SpaceNavigator, these are consecutive bytes following the channel number. 
                        # (but per-axis scaling can also be achieved by setting this value)
                        mappings = {"x":[1, 1, 2,1], "y":[1, 3, 4,-1], "z":[1,5,6,-1], "pitch":[2,1,2,-1], "roll":[2,3,4,-1], "yaw":[2,5,6,1]},    
    
                        # button states are specified as:
                        # [channel, data byte, left bit shift to be applied]
                        # If a message is received on the specified channel, the value of the data byte is applied
                        button_mapping = [(3,1,0)],
                        axis_scale = 350.0
                        ),        
    }

supported_devices = device_specs.keys()        
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
            for device_name,spec in device_specs.iteritems():
                if device.vendor_id == spec.hid_id[0] and device.product_id == spec.hid_id[1]:
                    devices.append(device_name)                        
    return devices
    
    
def open(callback=None, button_callback=None, device=None):
    """
    Open a 3D space navigator device. Makes this device the current active device, which enables the module-level read() and close()
    calls. For multiple devices, use the read() and close() calls on the returned object instead, and don't use the module-level calls.
    
    Parameters:        
        callback: If callback is provided, it is called on each HID update with a copy of the current state namedtuple  
        button_callback: If button_callback is provided, it is called on each button push, with the arguments (state_tuple, button_state) 
        device: name of device to open. Must be one of the values in supported_devices. If None, chooses the first supported device found.
    Returns:
        Device object if the device was opened successfully
        None if the device could not be opened
    """
    # only used if the module-level functions are used
    global _active_device
    
    # if no device name specified, look for any matching device and choose the first
    if device==None:
        all_devices = list_devices()
        if len(all_devices)>0:
            device = all_devices[0]
        else:
            return None
        
    all_hids = hid.find_all_hid_devices()
    if all_hids:
        for index, dev in enumerate(all_hids):
                spec = device_specs[device]
                if dev.vendor_id == spec.hid_id[0] and dev.product_id == spec.hid_id[1]:
                    print("%s found") % device
                    # create a copy of the device specification
                    new_device = copy.deepcopy(spec)
                    new_device.device = dev
                    # set the callbacks
                    new_device.callback = callback
                    new_device.button_callback = button_callback
                    # open the device and set the data handler
                    new_device.open()                    
                    dev.set_raw_data_handler(lambda x:new_device.process(x))   
                    _active_device = new_device
                    return new_device
        print("No supported devices found")
        return None
    else:
        print("No HID devices detected")
        return None
                            
def print_state(state):
    # simple default printer callback
    if state:
        print(" ".join(["%4s %+.2f"%(k,getattr(state,k)) for k in ['x', 'y', 'z', 'roll', 'pitch', 'yaw', 't']]))
        
def toggle_led(state, button):
    # Switch on the led on left push, off on right push
    if button&1:
        set_led(1)
    if button&2:
        set_led(0)
        
def set_led(state):    
    if _active_device:        
        _active_device.set_led(state)

if __name__ == '__main__':
    print("Devices found:\n\t%s" % "\n\t".join(list_devices()))
    open(callback=print_state, button_callback=toggle_led)
    set_led(0)
    while 1:        
        print read()
        sleep(1)
    
        
