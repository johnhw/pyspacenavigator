pyspacenavigator
================

3Dconnexion Space Navigator in Python using raw HID (windows only)

Implements a simple interface to the 6 DoF 3Dconnexion `Space
Navigator <http://www.3dconnexion.co.uk/products/spacemouse/spacenavigator.html>`__
device.

Requires `pywinusb <https://pypi.python.org/pypi/pywinusb/>`__ to access
HID data -- this is Windows only.

Basic Usage:
------------

::

    import spacenavigator
    import time

    success = spacenavigator.open()
    if success:
      while 1:
        state = spacenavigator.read()
        print state.x, state.y, state.z
        time.sleep(0.5)
      

State objects
-------------

State objects returned from read() have 7 attributes:
[t,x,y,z,roll,pitch,yaw].

-  t: timestamp in seconds since the script started.
-  x,y,z: translations in the range [-1.0, 1.0]
-  roll, pitch, yaw: rotations in the range [-1.0, 1.0].
