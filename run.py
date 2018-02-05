import os
import sys

from bot import BayMax

if not sys.version_info >= (3, 5):
    print("Install Python3.5 or later you idiot.")
    os._exit(1)

b = BayMax()
b.run()
