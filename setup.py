from distutils.core import setup

setup(
    name="spacenavigator",
    # packages = ['spacenavigator'], # this must be the same as the name above
    version="0.2.2",
    description="Python interface to the 3DConnexion Space Navigator",
    author="John Williamson",
    author_email="johnhw@gmail.com",
    url="https://github.com/johnhw/pyspacenavigator",  # use the URL to the github repo
    download_url="https://github.com/johnhw/pyspacenavigator/tarball/0.2.2",
    keywords=["spacenavigator", "3d", "6 DoF", "HID"],
    py_modules=["spacenavigator"],
    classifiers=[],
)
