"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import common.tools as tools
from pprint import pprint
import inspect, sys

# DO NOT EVER RENAME THIS FUNCTION BACK TO RELOAD 
# BECAUSE IT CAUSES A RECURSIVE IMPORT LOOP HUR HUR
def loadreload(object):
    if inspect.ismodule(object):
        module = object 
    else:
        module = inspect.getmodule(object)
    

    if not module:
        raise ImportError("Module for %s does not exist " % object)
    
    mod_name = module.__name__
    
    
    try:
        mod_imp = __import__(mod_name)
        del mod_imp
    except:
        raise ImportError("Couldn't import module %s " % mod_name)

    mod_path = inspect.getsourcefile(object)


    try:
        codebase = open(mod_path, 'rU').read()
    except:
        raise ImportError("Error opening file %s for error checking" % mod_path)

    
    return reload(module)
             
    