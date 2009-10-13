"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import logging

from twisted.internet.protocol import ReconnectingClientFactory

import common.config as config

import common.spanningtree as spanningtree
import common.log_levels as cll
import common.tools as tools
import common.uid_types as uid
import common.ext as ext
import common.reloader as reloader


""" 
    Reconnecting Factory which generates and controls 
    SpanningTree12() clients.
"""
class SpanningTreeFactory(ReconnectingClientFactory):

    protocol = spanningtree.SpanningTree12
    config_file = ''
    """
        Our modules and capabilities are set here.
        TODO: Add more of our own capabilities in future.
    """
    modules = []
    capabilities = {}
    loaded_extensions = {}
    
    """ 
        Initiates basic connection attempts and sets
        non-static values.
    """
    def __init__(self, cfg,config_file):
        self.connector = None
        self.cfg = cfg
        self.config_file = config_file
        self.maxDelay = self.cfg.reconnect.max_delay
        self.initialDelay = self.cfg.reconnect.initial_delay
        self.factor = self.cfg.reconnect.factor_incr
    
        self.capabilities = cfg.capabilities
        self.modules = cfg.modules
        
        self.log = logging.getLogger('ST_FACTORY')
        self.log.log(cll.level.INFO,'Starting Spanning Tree')
    
        

    def reload_config(self):
        self.cfg = config.Config(file(self.config_file))
        return self.config_file
        
        
    """
        Called when the factory client has started
        connecting. Resets all per-connection  
        variables back to their defaults, and re-
        generates a HMAC challenge string using 
        tools.hmac_challenge_string() which is 
        placed into the capabilities dictionary.
    """
    def startedConnecting(self, connector): 
        self.log.log(cll.level.INFO,'Connecting to %s:%s' % (self.cfg.peer_server.address, self.cfg.peer_server.port))

        # Generate a new HMAC challenge on every connection attempt
        self.capabilities['CHALLENGE'] = tools.hmac_challenge_string()

        # Reset the recorded peer UID
        self.peer_uid = None
        
        # Reset HMAC usage just incase peer does not send a challenge this time
        self.use_hmac = False
        
        # Setup a User / Server UID lookup table 
        self.uid = {}
        
        # A map of server names to UID's
        self.server_names = {}
        
        # Clear the list of pseudoclients
        self.pseudoclients = {}
        
        # Clear the list of extensions
        self.extensions = []
        
        # Clear the list of hooks we allow from extensions
        self.hook = {}
        
        # We have not yet negotiated a fully authenticated + synced connection
        self.connected = False
        
        # Reset our BURST status
        self.is_bursting = False

        # Reset channel modes list
        self.chanmodes = {}
        
        # Reset user modes list
        self.usermodes = {}
        
        # Reset prefix modes list
        self.prefix = {}
        
        
    """
        This function creates instances of all 'Extension' classes
        that exist in the 'extensions' directory.
        They are created automagically if they subclass the correct
        BaseExtension type from common.ext.BaseExtension, with the
        current Receiver object as the only argument.
    """
    def insert_extensions(self,connector):
      
        
        nmp = []
      
        avail_ext = dict(tools.find_classes('extensions'))

        # Clear hooks before loading, if this is a "rehash"
        # we want the new hooks to take precedence
        self.hook = {}

        for name in self.cfg.extensions:
            ext_l = avail_ext.get(name,None)
           
            if not ext_l:
                nmp.append(name)
                
            elif issubclass(ext_l,ext.BaseExtension):
                ivr = None
                try:
                    # Create the object of this class by reloading the
                    # module if necessary, then call its init method
                    # with getattr. This stops it taking multiple 
                    # reloads for one to take effect.
                    
                    mod = reloader.loadreload(ext_l)
                    ifunc = getattr(mod, name)
                    ivr = ifunc(connector)
                    
                except (ImportError, RuntimeError), e:
                    self.log.log(cll.level.ERROR,'%s' % str(e))
                    
                    if name in self.loaded_extensions:
                        del self.loaded_extensions[name]
                else:
                    if name not in self.loaded_extensions:
                        self.loaded_extensions[name] = ivr
        
        self.log.log(cll.level.INFO,'Loaded %s' % ', '.join(self.loaded_extensions))
        
      
        if nmp:
            self.log.log(cll.level.WARNING,'Failed to load %s' % ', '.join(nmp))
            
    
    """
        Appends a hook on the given function name by appending
        it to the list of functions to be called when the function
        calls its' hook name.
    """
    def add_hook(self,hookname,ext):
        h = self.hook.get(hookname,[])
        h.append(ext)
        
        self.hook[hookname] = h
        
    
    """ 
        Override factory buildprotocol to allow insertion of
        extensions into the protocol object.
    """
    def buildProtocol(self,addr):
        p = self.protocol()
        p.factory = self
        
        self.insert_extensions(p)

        return p
        
    """
        Called when the factory client has lost
        connection, this resets the connected 
        status and calls the parent factory method
        which should attempt to reconnect to the 
        peer server.
    """
    def clientConnectionLost(self, connector, reason):
        self.connected = False
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

        
    """
        Called when the factory client cannot
        connect to the peer server, this calls
        the parent factory method which should 
        attempt another connection to the peer
        server.
    """
    def clientConnectionFailed(self, connector, reason):
        self.connected = False
        ReconnectingClientFactory.clientConnectionFailed(self, connector,reason)
    