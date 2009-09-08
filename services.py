#!/usr/bin/env python
"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

__servicesname__        = 'PyServices'
__version__             = '0.2a'
__author__              = 'B. Agricola <maz@lawlr.us>'


import os, getopt, logging, traceback, time, re, inspect, sys

from pprint import pprint

from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet import reactor, defer, stdio

import common.consoleinteraction as consoleinteraction
import common.spanningtree as spanningtree
import common.colour as colour
import common.config as config
import common.log_levels as cll
import common.tools as tools
import common.uid_types as uid
import common.ext as ext
import common.reloader as reloader

from common.cmd_types import cmd as cmd
from common.cmd_types import sr_assoc as sr_assoc

        

        
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
    loaded_extensions = []
    
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
        
        self.server_version = '%s-%s (%s) %s :%s' % (__servicesname__,__version__,__author__,self.cfg.server.name,self.cfg.server.description)

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

                try:
                    # Create the object of this class by reloading the
                    # module if necessary, then call its init method
                    # with getattr. This stops it taking multiple 
                    # reloads for one to take effect.
                    
                    mod = reloader.loadreload(ext_l)
                    ifunc = getattr(mod, name)
                    ifunc(connector)
                    
                except (ImportError, RuntimeError), e:
                    self.log.log(cll.level.ERROR,'%s' % str(e))
                    
                    if name in self.loaded_extensions:
                        self.loaded_extensions.remove(name)
                else:
                    if name not in self.loaded_extensions:
                        self.loaded_extensions.append(name)
        
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
    
    
"""	
    This is the main() method which initiates
    program flow. It sets up program-wide log
    systems for both file and console, and
    then calls the Twisted.net reactor to 
    start connection attempts.
"""
def main():

    # Set defaults for runtime variables
    debug_level = 10
    log = None
    
    # Import command line optiosn / config specifier
    options, config_file = getopt.getopt(sys.argv[1:],'d:l:c:',['debug=','log=','config='])
    
    # If config file was not set as the last argument to the command line, set a default
    if not config_file:
        config_file = './services.conf'
    
    # Set runtime variables from the command line options 
    for opt, arg in options:
    
        if opt in ('-d', '--debug'):
            debug_level = 50 - int(arg)
            
        elif opt in ('-l', '--log'):
            log = arg
            
        elif opt in ('--config'):
                config_file = arg

    # Check that config file exists and is readable
    if not os.access(config_file,os.F_OK|os.R_OK):
        print "\nConfig file %s does not exist.\n" % config_file
        sys.exit(1)
        
    # Load config file
    cfg = config.Config(file(config_file))
    
    
    # If log location is not set by command line, set it via config file
    if not log:
        log = cfg.logging.location
        
        
    # Set up file logging
    format_string = cfg.logging.file_format
    log_format = logging.Formatter(format_string)
    logging.basicConfig(level=debug_level, format=format_string, filename=log,filemode='a')

    
    # Set up console (+ colour) logging
    console_log = logging.StreamHandler()
    console_log.setLevel(logging.DEBUG)
    color_format = colour.formatter_message(cfg.logging.console_format)
    formatter = colour.ColoredFormatter(color_format,cfg.logging.console_max_width,cfg.logging.console_multiline_offset)
    console_log.setFormatter(formatter)
    logging.getLogger('').addHandler(console_log)

    logging.getLogger('MAIN').log(cll.level.INFO,'Starting Up')
    
    # Initiate console handler
    if cfg.console.enable_input:
        stdio_handler = consoleinteraction.ConsoleInteraction(cfg,config_file,initiate_spanningtree)
        chandler = stdio.StandardIO(stdio_handler)
        
    else:
        initiate_spanningtree(cfg,config_file)
        
    #Initiate connection attempts
    
    if cfg.debug.profile.enabled:
    
        logging.getLogger('MAIN').log(cll.level.WARNING,'Running in PROFILE mode, this may cause excessive slowness!!')
        import hotshot, hotshot.stats
        
        if not cfg.debug.profile.file:
            logging.getLogger('MAIN').log(cll.level.ERROR,'Cannot profile without a filename specified')
            sys.exit(1)
            
        if os.access(cfg.debug.profile.file,os.F_OK|os.W_OK):
            logging.getLogger('MAIN').log(cll.level.WARNING,'Profile file %s already exists, truncating' % cfg.debug.profile.file)
            
            try:
                os.remove(cfg.debug.profile.file)
            except OSError:
                logging.getLogger('MAIN').log(cll.level.ERROR,'Profile file %s could not be deleted' % cfg.debug.profile.file)
                sys.exit(1)
                
        prof = hotshot.Profile(cfg.debug.profile.file)
        
        prof.start()
        reactor.run()
        prof.stop()
        
        prof.close()
        
        stats = hotshot.stats.load(cfg.debug.profile.file)
        stats.strip_dirs()
        stats.sort_stats('time', 'calls')
        stats.print_stats(100)
        
    else:
        reactor.run()
    
    
def initiate_spanningtree(cfg,config_file):
    factory = SpanningTreeFactory(cfg,config_file)
    connector = reactor.connectTCP(cfg.peer_server.address, cfg.peer_server.port, factory)

    return (factory,connector)

        
"""
    This runs the main() method via psyco
    if the file is executed directly and 
    not imported in another python file.
"""
if __name__ == "__main__":   
    
    try:
        import psyco
        psyco.full()
    except ImportError:
        pass
    
    main()
    
    
    
    
