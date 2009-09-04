"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import logging, traceback
from pprint import pprint as pprint

from twisted.protocols.basic import LineOnlyReceiver
from twisted.internet import reactor
import common.colour as colour
import common.config as config

import common.uid_types as uid
import common.log_levels as cll

class ConsoleInteraction(LineOnlyReceiver):
    delimiter = '\n'
    norm_prompt_string = colour.format_colour(colour.GREEN,'>>> ')
    raw_prompt_string = colour.format_colour(colour.RED,'!!! ')
    
    def __init__(self,cfg,config_file,linked_generator):
        self.logging = True
        self.log = logging.getLogger('CON_RECEIVER')
        self.raw = False
        self.ready_for_cmd = False
        self.linked_generator = linked_generator
        self.cfg = cfg
        self.config_file = config_file
    def prompt(self):
        if self.raw:
            self.transport.write(self.raw_prompt_string)
        else:
            self.transport.write(self.norm_prompt_string)
        
    def connectionMade(self):
        self.factory,self.connector = self.linked_generator(self.cfg,self.config_file)
        
    

    def lineReceived(self, line):
        line = line.strip()
        
        if not line and self.factory.connected:
            self.prompt()
            self.ready_for_cmd = True
            return
            
        elif self.ready_for_cmd and line.upper() == 'RAW':
            self.raw = True
            self.prompt()
            return
            
        elif not self.factory.connected or not self.ready_for_cmd:
            return
            
        if self.raw:

            self.issueCommand(line)
            self.raw = False
            self.ready_for_cmd = False
        else:
            self.ready_for_cmd = not self.handleCommand(line)
        
        
    def handleCommand(self,line):
    
        tokens = line.split(' ')

        if len(tokens) > 1:
            cmd = tokens.pop(0)
            subcmd = tokens.pop(0).upper()
        else:
            cmd = line.upper()
            subcmd = ''
            
        try:
        
            method = getattr(self, "con_%s" % cmd.lower(), None)
        
            if method is not None:
                
                # !!! TODO: This *MAY* need changing to allow
                # !!! the method to run in a separate thread.
                _v = method(subcmd, tokens)
                    
                return _v
            else:
                # Default to the st_receive_unknown method if
                # a class was not found.
                return self.con_unknown(line,cmd,subcmd,tokens)
                
        except Exception, e:
            # Called method raised an uncaught exception, catch it here and 
            # Drop a traceback into the log (EWW)
            self.log.log(cll.level.ERROR,'Uncaught Exception during console command delegation: %s' % e.message)
            
            # !!! TODO: Find a better way to log tracebacks
            self.log.log(cll.level.DEBUG,traceback.format_exc())
            self.connector.transport.protocol.quit()
            

    def con_config(self,cmd,tokens):
        if cmd == 'RELOAD':
            cfg_file = self.factory.reload_config()
            self.log.log(cll.level.INFO,'Reloaded config from %s' % cfg_file)
        else:
            return False
            
    def con_log(self,cmd,tokens):
        if cmd == 'TOGGLE':
            if self.logging:
                self.transport.write('Logging %s.' % colour.format_colour(colour.RED,'Disabled') + self.delimiter)
                self.log.log(cll.level.INFO,'Logging turned off by console')
                logging.disable(500)
                self.logging = False
            else:
                logging.disable(0)
                self.transport.write('Logging %s.' % colour.format_colour(colour.GREEN,'Enabled') + self.delimiter)
                self.log.log(cll.level.INFO,'Logging turned on by console')
                self.logging = True
            
            return True
        else:
            return False
    
    def con_list(self,cmd,tokens):
        if cmd.startswith('UID'):
            list = colour.format_colour(colour.YELLOW,"UID's: ") + ', '.join(self.factory.uid)
        
        elif cmd.startswith('USER'):
            list = colour.format_colour(colour.YELLOW,"USERS: ") + ', '.join([user.nick for user in self.factory.uid.values() if isinstance(user,uid.User)])
        
        elif cmd.startswith('CHANNEL'):
            list = colour.format_colour(colour.YELLOW,"CHANNELS: ") + ', '.join([channel.name for channel in self.factory.uid.values() if isinstance(channel,uid.Channel)])
            
        else:
            self.transport.write(colour.format_colour(colour.RED,'Unknown list type %s' % (cmd)) + self.delimiter)
            self.prompt()
            return False
            
        self.transport.write(list + self.delimiter)	
        return True
        
    def con_quit(self,subcmd,tokens):
        self.log.log(cll.level.WARNING,'Server exit forced by console QUIT!')
        self.connector.transport.protocol.quit()
        return True
        
    def con_unknown(self,line,cmd,subcmd,tokens):
        self.transport.write(colour.format_colour(colour.RED,'Unknown command %s' % (line)) + self.delimiter)
        self.prompt()
        return False
        
    def issueCommand(self, command):
        # write to the connector's transport, not the one writing on stdout
        self.connector.transport.protocol._sendLine(command)
        