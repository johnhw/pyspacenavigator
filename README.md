# py3dx
3Dconnexion Space Navigator in Python using raw HID (windows only)

Implements a simple interface to the 6 DoF 3Dconnexion [Space Navigator](http://www.3dconnexion.co.uk/products/spacemouse/spacenavigator.html) device.

Usage:

    import spacenavigator
    import time
    
    success = spacenavigator.open()
    if success:
      while 1:
        state = spacenavigator.read()
        print state.x, state.y, state.z
        time.sleep(0.5)
      
      
State objects have 7 attributes: [t,x,y,z,roll,pitch,yaw]. T is a timestamp in seconds since the script started. x,y,z are translations in the range [-1.0, 1.0] and roll, pitch, yaw are rotations in the range [-1.0, 1.0].


