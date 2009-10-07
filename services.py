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
__version__             = '0.55'
__author__              = 'MaZ <maz@lawlr.us>'


import os, getopt, logging, traceback, time, re, inspect, sys

from pprint import pprint

from twisted.internet import reactor, defer, stdio

import common.consoleinteraction as consoleinteraction
import common.spanningtreefactory as spanningtreefactory

import common.daemon as daemon
import common.colour as colour
import common.config as config
import common.log_levels as cll
import common.tools as tools
import common.uid_types as uid
import common.ext as ext
import common.reloader as reloader

from common.cmd_types import cmd as cmd
from common.cmd_types import sr_assoc as sr_assoc

    
def initiate_spanningtree(cfg,config_file):
    factory = spanningtreefactory.SpanningTreeFactory(cfg,config_file)
    factory.server_version = '%s-%s (%s) %s :%s' % (__servicesname__,__version__,__author__,cfg.server.name,cfg.server.description)

    connector = reactor.connectTCP(cfg.peer_server.address, cfg.peer_server.port, factory)

    return (factory,connector)

    
    
class ServicesDaemon(daemon.Daemon):
    default_config = './services.conf'
    

    def run(self):
        if self.cfg.console.enable_input:
            stdio_handler = consoleinteraction.ConsoleInteraction(self.cfg,self.config_filename,initiate_spanningtree)
            chandler = stdio.StandardIO(stdio_handler)
            
        else:
            initiate_spanningtree(self.cfg,self.config_filename)
        
        reactor.run()
        
  
    def parse_config(self):
        self.cfg = config.Config(file(self.config_filename))
        
        if self.cfg.console.enable_input:
            self.daemonize = False
            
        self.root_dir = self.cfg.daemon.root_dir
        self.pid_file = self.cfg.daemon.pid_file
        self.uid = self.cfg.daemon.uid
        self.gid = self.cfg.daemon.gid
        
        self.log_file = self.cfg.logging.location
        
     
    def start_logging(self):
        # Set up file logging
        format_string = self.cfg.logging.file_format
        log_format = logging.Formatter(format_string)
        logging.basicConfig(level=self.cfg.logging.debug_level, format=format_string, filename=self.log_file,filemode='a')

        
        if not self.daemonize:
            # Set up console (+ colour) logging
            console_log = logging.StreamHandler()
            console_log.setLevel(logging.DEBUG)
            color_format = colour.formatter_message(self.cfg.logging.console_format)
            formatter = colour.ColoredFormatter(color_format,self.cfg.logging.console_max_width,self.cfg.logging.console_multiline_offset)
            console_log.setFormatter(formatter)
            logging.getLogger('').addHandler(console_log)

        logging.getLogger('MAIN').log(cll.level.INFO,'Starting Up')
    
    
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
    
    
    ServicesDaemon(os.path.basename(__file__)).main()
    
    
    
    
