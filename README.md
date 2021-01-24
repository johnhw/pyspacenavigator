# pyspacenavigator
3Dconnexion Space Navigator in Python using raw HID (Windows only). Note: you **don't** need to install or use any of the drivers or 3Dconnexion software to use this package. It interfaces with the controller directly.

Implements a simple interface to the 6 DoF 3Dconnexion [Space Navigator](http://www.3dconnexion.co.uk/products/spacemouse/spacenavigator.html) device as well as similar devices. The following 3dconnexion devices are supported:

* SpaceNavigator
* SpaceMouse Pro
* SpaceMouse Pro Wireless
* SpaceMouse Wireless
* 3Dconnexion Universal Receiver
* SpaceMouse Compact
* SpacePilot Pro

Requires [pywinusb](https://pypi.python.org/pypi/pywinusb/) to access HID data -- this is Windows only.

## Basic Usage:

    import spacenavigator
    import time
    
    success = spacenavigator.open()
    if success:
      while 1:
        state = spacenavigator.read()
        print(state.x, state.y, state.z)
        time.sleep(0.5)
      
## State objects      
State objects returned from read() have 7 attributes: [t,x,y,z,roll,pitch,yaw,button].

* t: timestamp in seconds since the script started. 
* x,y,z: translations in the range [-1.0, 1.0] 
* roll, pitch, yaw: rotations in the range [-1.0, 1.0].
* button: list of button states (0 or 1), in order specified in the device specifier

## API
    open(callback=None, button_callback=None, device=None)      
        Open a 3D space navigator device. Makes this device the current active device, which enables the module-level read() and close()
        calls. For multiple devices, use the read() and close() calls on the returned object instead, and don't use the module-level calls.
    
        Parameters:        
            callback: If callback is provided, it is called on each HID update with a copy of the current state namedtuple  
            button_callback: If button_callback is provided, it is called on each button push, with the arguments (state_tuple, button_state) 
            device: name of device to open, as a string like "SpaceNavigator". Must be one of the values in `supported_devices`. 
                    If `None`, chooses the first supported device found.            
        Returns:
            Device object if the device was opened successfully
            None if the device could not be opened
        
    read()              Return a namedtuple giving the current device state (t,x,y,z,roll,pitch,yaw,button)
    close()             Close the connection to the current device, if it is open
    set_led(state)      Set the status of the current devices LED to either on (True) or off (False)
    list_devices()      Return a list of supported devices found, or an empty list if none found
    
    
open() returns a DeviceSpec object. If you have multiple 3Dconnexion devices, you can use the object-oriented API to access them individually.
Each object has the following API, which functions exactly as the above API, but on a per-device basis:

    dev.open()          Opens the connection (this is always called by the module-level open command, 
                        so you should not need to use it unless you have called close())
    dev.read()          Return the state of the device as namedtuple [t,x,y,z,roll,pitch,yaw,button]
    dev.close()         Close this device
    dev.set_led(state)  Set the state of the LED on the device to on (True) or off (False)
    
There are also attributes:
    
    dev.connected       True if the device is connected, False otherwise
    dev.state           Convenience property which returns the same value as read()
    
    
    
    


