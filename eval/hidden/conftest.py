import os
import sys

# The run directory under test is passed in via SHOP_ROOT.
sys.path.insert(0, os.path.join(os.environ["SHOP_ROOT"], "src"))
