import logging
import log_levels as cll
import tools
from pprint import pprint as pprint
class BaseExtension(object):
    
    default_hook_methods = r'^(st|ps)_'
    
    def __init__(self,protocol):
        self.protocol = protocol
        self.factory = protocol.factory
        
        self.name = self.__class__.__name__
        self.log = logging.getLogger(self.name.upper())
        
        self.log.log(cll.level.INFO,'Initializing %s' % self.name)

        # Automatically add hooks for any st_ methods
        # which exist in this extension.
        self.hook_find()
        
    def hook_find(self):
        self.log.log(cll.level.VERBOSE,'Requesting all hooks matching %s in %s...' % (self.default_hook_methods,self.name))
        hooks = []
        for hook in tools.find_names(self,self.default_hook_methods):
            self.factory.add_hook(hook,self)
            hooks.append(hook)
        self.log.log(cll.level.VERBOSE,'Requested hooks on %s' % (', '.join(hooks)))	
            
        
