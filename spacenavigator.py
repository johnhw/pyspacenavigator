from time import sleep
import pywinusb.hid as hid
from collections import namedtuple
import timeit

# clock for timing
high_acc_clock = timeit.default_timer

## Simple HID code to read data from the 3dconnexion Space Navigator
mappings={"x":[1, 1, 2,1], "y":[1, 3, 4,-1], "z":[1,5,6,-1], "pitch":[2,1,2,-1], "roll":[2,3,4,-1], "yaw":[2,5,6,1], "button":[3,1,2,1]}
channel1_mappings = {k:v for k,v in mappings.iteritems() if v[0]==1}
channel2_mappings = {k:v for k,v in mappings.iteritems() if v[0]==2}

# the ID for the space navigator
space_navigator_hid_id = [0x046d,0xc626]

# _space_navigator_dict is a dictionary mapping [t,x,y,z,pitch,yaw,roll,button] to their latest values.
# it is empty if the device has not been opened yet
_space_navigator_dict = {"button":0}
SpaceNavigator = namedtuple('SpaceNavigator', ['t','x', 'y', 'z', 'roll', 'pitch', 'yaw', 'button'])
_space_navigator = None
_device = None

# convert two 8 bit bytes to a signed 16 bit integer
def byte_2(y1,y2):
    x = (y1) | (y2<<8)
    if x>=32768:
        x = -(65536-x)
    return x
    

def callback_handler(data, callback=None, button_callback=None):
    global _space_navigator
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
    if data[0]==1:
        for name,(chan,b1,b2,flip) in channel1_mappings.iteritems():
            _space_navigator_dict[name] = flip*byte_2(data[b1], data[b2])/350.0
    elif data[0]==2:
        for name,(chan,b1,b2,flip) in channel2_mappings.iteritems():
            _space_navigator_dict[name] = flip*byte_2(data[b1], data[b2])/350.0
    elif data[0]==3:
        button_pushed = True
        _space_navigator_dict["button"] = data[1]
    else:
        pass
        
    _space_navigator_dict["t"] = high_acc_clock()
    
    if len(_space_navigator_dict)==8:
        _space_navigator = SpaceNavigator(**_space_navigator_dict)
    
    if callback:
        callback(_space_navigator)
        
    if button_callback and button_pushed:
        button_callback(_space_navigator, data[1])
        
# Usage ID for the status LED
_led_usage = hid.get_full_usage_id(0x8, 0x4b) 

def set_led(state):
    """Set the LED state to state (True or False)"""
    if _device:
        reports = _device.find_output_reports()
        for report in reports:
            if _led_usage in report:
                report[_led_usage] = state
                report.send()
        
def close():
    """Close the device, if it is open"""
    if _device:
        _device.close()
        _device = None
  
def read():
    """Return the current state of the navigation controller.
    Returns:
        state: {t,x,y,z,pitch,yaw,roll} dictionary
        None if the device is not open.
    """
    return tuple_state
    
def open(callback=None, button_callback=None):
    """
    Open the 3D space navigator device.
    
    Parameters:
        callback: If callback is provided, it is called on each HID update with a copy of the current state dictionary   
        button_callback: If button_callback is provided, it is called on each button push, with the arguments (state_tuple, button_state) 
    Returns:
        True if the device was opened successfully
        False if the device could not be opened
    """
    global _device
    # scan for HID devices, returns True if the device could be opened
    all_hids = hid.find_all_hid_devices()
    if all_hids:
        for index, device in enumerate(all_hids):
            if device.vendor_id == space_navigator_hid_id[0] and device.product_id == space_navigator_hid_id[1]:
                print("3Dconnexion SpaceNavigator found")                
                device.open()
                if callback or button_callback:
                    device.set_raw_data_handler(lambda x:callback_handler(x,callback=callback, button_callback=button_callback))
                else:
                    device.set_raw_data_handler(callback_handler)
                _device = device
                return True
        print("No 3Dconnexion SpaceNavigator found")
        return False
    else:
        print("No HID devices detected")
        return False
     
def print_state(state):
    # simple default printer callback
    if state:
        print " ".join(["%4s %+.2f"%(k,getattr(state,k)) for k in ['x', 'y', 'z', 'roll', 'pitch', 'yaw', 't']])
        
def toggle_led(state, button):
    # Switch on the led on left push, off on right push
    if button&1:
        set_led(1)
    if button&2:
        set_led(0)

if __name__ == '__main__':
    open(callback=print_state, button_callback=toggle_led)
    set_led(0)
    while 1:
        sleep(1)
    
        
