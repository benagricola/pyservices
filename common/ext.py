import logging
import log_levels as cll
import tools
class BaseExtension(object):
    
    default_hook_methods = r'^(st|ps)_'
    
    def __init__(self,receiver):
        self.receiver = receiver
        self.name = self.__class__.__name__
        self.log = logging.getLogger(self.name.upper())
        
        # Automatically add hooks for any st_ methods
        # which exist in this extension.
        self.hook_find()
        
    def hook_find(self):
        self.log.log(cll.level.VERBOSE,'Requesting all hooks matching %s in %s...' % (self.default_hook_methods,self.name))
        hooks = []
        for hook in tools.find_methods(self,self.default_hook_methods):
            self.receiver.add_hook(hook,self)
            hooks.append(hook)
        self.log.log(cll.level.VERBOSE,'Requested hooks on %s' % (', '.join(hooks)))	
            
        
