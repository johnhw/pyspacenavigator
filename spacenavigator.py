
from time import sleep
import pywinusb.hid as hid
from collections import namedtuple
import timeit
import copy
from pywinusb.hid import usage_pages, helpers, winapi    

# current version number
__version__=  "0.1.6"

# clock for timing
high_acc_clock = timeit.default_timer

GENERIC_PAGE = 0x1
BUTTON_PAGE= 0x9
LED_PAGE = 0x8
MULTI_AXIS_CONTROLLER_CAP = 0x8

HID_AXIS_MAP = {0x30:"x", 0x31:"y", 0x32:"z", 0x34:"roll", 0x33:"pitch", 0x35:"yaw"}

# axis mappings are specified as:
# [channel, byte1, byte2, scale]; scale is usually just -1 or 1 and multiplies the result by this value 
# (but per-axis scaling can also be achieved by setting this value)
# byte1 and byte2 are indices into the HID array indicating the two bytes to read to form the value for this axis
# For the SpaceNavigator, these are consecutive bytes following the channel number.                         
AxisSpec = namedtuple('AxisSpec', ['channel', 'byte1', 'byte2', 'scale'])


# button states are specified as:
# [channel, data byte,  bit of byte, index to write to]
# If a message is received on the specified channel, the value of the data byte is set in the button bit array                       
ButtonSpec = namedtuple('ButtonSpec', ['channel', 'byte', 'bit'])
                      

## Simple HID code to read data from the 3dconnexion devices

# convert two 8 bit bytes to a signed 16 bit integer
def to_int16(y1,y2):
    x = (y1) | (y2<<8)
    if x>=32768:
        x = -(65536-x)
    return x

# tuple for 6DOF results
SpaceNavigator = namedtuple('SpaceNavigator', ['t','x', 'y', 'z', 'roll', 'pitch', 'yaw', 'buttons'])

class DeviceSpec(object):
    """Holds the specification of a single 3Dconnexion device"""
    def __init__(self, name):
        self.name = name
       
        # initialise to a vector of 0s for each state
        self.dict_state = {"buttons":[]}
        self.tuple_state = SpaceNavigator(-1,0,0,0,0,0,0,[])
        # start in disconnected state
        self.device = None        
        self.callback = None
        self.button_callback = None

    def describe_connection(self):
        """Return string representation of the device, including
        the connection state"""
        if self.device==None:
            return "%s [disconnected]" % (self.name)
        else:
            return "%s [serial: %s]" % (self.device, self.serial_number)

       
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
        # doesn't seem to work on 3dconnexion devices...
        # serial number will be a byte string, we convert to a hex id                    
        self.serial_number = "".join(["%02X"%ord(char) for char in self.device.serial_number])
        self.analyse_usages()
                   
    def analyse_usages(self):
        """Work out the axis, button and LED mappings from the usage data"""
        if self.device.hid_caps.usage_page==GENERIC_PAGE and self.device.hid_caps.usage_page==MULTI_AXIS_CONTROLLER_CAP:
            print("Found multi-axis device")            
            
        inputs = self.device.usages_storage.get(winapi.HidP_Input, [])
        for hid_input in inputs:
            all_items = hid_input.inspect()            
            
            usage_page = all_items["usage_page"]       
            
            if usage_page==BUTTON_PAGE:                        
                # buttons are usage ranges
                self.dict_state["buttons"]  += [0 for i in range(all_items["usage_max"]+1-all_items["usage_min"])]
                
                button_handler = lambda value, id: self.button_handler(0, value)
                self.device.add_event_handler(hid.get_full_usage_id(usage_page, all_items["usage_min"]), button_handler)                    
                    
                print(all_items)
                
                    

            if "usage" in all_items:
                usage = all_items["usage"]
                # these are axes to be mapped     
                if usage_page==GENERIC_PAGE:                             
                        usage_dev = usage_pages.HidUsage(usage_page, usage)
                        if usage in HID_AXIS_MAP:
                            # get the name and range of this axis
                            axis_name = HID_AXIS_MAP[usage]
                            axis_min = all_items["logical_min"]
                            axis_max = all_items["logical_max"]                            
                            axis_handler = lambda value, id, axis_name=axis_name,  axis_min=axis_min, axis_max=axis_max, : self.axis_handler(axis_name, value, axis_min, axis_max)
                            self.device.add_event_handler(hid.get_full_usage_id(usage_page, usage), axis_handler)                                                                        
                
                
            
        # outputs (just LEDs)
        outputs = self.device.usages_storage.get(winapi.HidP_Output, [])
        for hid_output in outputs:
            all_items = hid_output.inspect()
            usage_page = all_items["usage_page"]            
            if usage_page == LED_PAGE:                
                # found an LED, map it (just one LED assumed)
                self.led_usage = hid.get_full_usage_id(usage_page, all_items["usage"])
                
        
    def button_handler(self, button_id,  state):      
        print(button_id, state)  
        self.dict_state["buttons"][button_id] = state        
        if self.button_callback:            
            self.button_callback(self.tuple_state, self.tuple_state.buttons)

    def axis_handler(self, axis, value, min_val, max_val):
        # these are really signed 16 bit ints
        if value>32767:
            value = -(65536-value)
        value = (float(value) - min_val) / (max_val-min_val)        
        self.dict_state["t"] = high_acc_clock()
        # scale to -1, 1 range
        self.dict_state[axis] = 2*(value-0.5)

        # only call the callback on the x axis
        # as the device outputs all axes in a round-robin fashion
        if axis=="x":
            if len(self.dict_state)==8:
                self.tuple_state = SpaceNavigator(**self.dict_state)
            if self.callback:
                self.callback(self.tuple_state)   

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
            
   


supported_devices = ["SpaceNavigator", "SpaceMouse Pro Wireless"]

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
            if device.product_name in supported_devices:
                devices.append(device.product_name)                        
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
                
                if dev.product_name == device:
                    print("%s found" % device)
                    # create a copy of the device specification
                    new_device = DeviceSpec(device)
                    new_device.device = dev                                       
                    # set the callbacks
                    new_device.callback = callback
                    new_device.button_callback = button_callback
                    # open the device and set the data handler
                    new_device.open()                    
                    #dev.set_raw_data_handler(lambda x:new_device.process(x))   
                    _active_device = new_device
                    return new_device                    
        print("No supported devices found")
        return None
    else:
        print("No HID devices detected")
        return None
                            
def print_state(state):
    # simple default printer callback
    return
    if state:
        print(" ".join(["%4s %+.2f"%(k,getattr(state,k)) for k in ['x', 'y', 'z', 'roll', 'pitch', 'yaw', 't']]))
        
def toggle_led(state, buttons):
    print(buttons)
    return
    # Switch on the led on left push, off on right push
    if buttons[0] == 1:
        set_led(1)
    if buttons[1] == 1:
        set_led(0)
        
def set_led(state):    
    if _active_device:        
        _active_device.set_led(state)

if __name__ == '__main__':
    
    print("Devices found:\n\t%s" % "\n\t".join(list_devices()))
    dev = open(callback=print_state, button_callback=toggle_led)
    print(dev.describe_connection())
    
    if dev:
        dev.set_led(0)    
        while 1:                    
            sleep(1)
            
        
        
