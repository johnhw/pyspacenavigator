# pyspacenavigator
3Dconnexion Space Navigator in Python using raw HID (windows only)

Implements a simple interface to the 6 DoF 3Dconnexion [Space Navigator](http://www.3dconnexion.co.uk/products/spacemouse/spacenavigator.html) device.

Requires [pywinusb](https://pypi.python.org/pypi/pywinusb/) to access HID data -- this is Windows only.

## Basic Usage:

    import spacenavigator
    import time
    
    success = spacenavigator.open()
    if success:
      while 1:
        state = spacenavigator.read()
        print state.x, state.y, state.z
        time.sleep(0.5)
      
## State objects      
State objects returned from read() have 7 attributes: [t,x,y,z,roll,pitch,yaw,button].

* t: timestamp in seconds since the script started. 
* x,y,z: translations in the range [-1.0, 1.0] 
* roll, pitch, yaw: rotations in the range [-1.0, 1.0].
* button: bit 1: left button, bit 2: right button (e.g. 1=left, 2=right, 3=left+right, 0=none)

## API
    open(callback=None, button_callback=None)      Open a connection to the device. Returns True on success
                                                   If callback is given, it is called on each state change. 
                                                   button_callback is called each time a button is pressed or released.
    
    read()              Return a namedtuple giving the current device state (t,x,y,z,roll,pitch,yaw,button)
    close()             Close the connection to the device, if it is open
    set_led(state)      Set the status of the LED to either on (True) or off (False)
    


