"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""


import os, getopt, logging, traceback, time, re, inspect, sys, time


from twisted.protocols.basic import LineOnlyReceiver
from twisted.internet import reactor,defer

from pprint import pprint as pprint

import common.log_levels as cll
import common.tools as tools
import common.uid_types as uid
import common.ext as ext

from common.cmd_types import cmd as cmd
from common.cmd_types import sr_assoc as sr_assoc


""" 
Implements the Spanning Tree 1.2.x protocol used by InspIRCd as a 
Twisted.net LineOnlyReceiver.
Most of this code deals with connection negotiation and synchronization,
with actual functionality once connected dealt with by external handlers
implemented elsewhere.
""" 
class SpanningTree12(LineOnlyReceiver):
    
        
    """ 
        Called when connection to remote port succeeds.
        Initiates the handshake protocol by calling st_send_capab().
    """
    def connectionMade(self):
        self.log = logging.getLogger('ST_RECEIVER')
        
        self.log.log(cll.level.INFO,'Connection accepted on port %s' % (self.factory.cfg.peer_server.port))
        self.factory.resetDelay()
        self.log.log(cll.level.VERBOSE,'Inserting custom hooks')
        
        
        self.execute_hook()
        self.st_send_capab()
        
        
    """
        Called when another method wants to terminate
        the application.
    """
    def quit(self,executehook = True):
        if executehook:
            self.execute_hook()
            
            
            
            def forcequit():
                self.log.log(cll.level.DEBUG,'Attempting to disconnect cleanly')
                self.factory.stopTrying()
                self.transport.loseConnection()
                
            reactor.callLater(5, forcequit)
            reactor.callLater(10, reactor.stop)
        
        else:
            self.factory.stopTrying()
            reactor.stop()
        
    

    
        
    """ Called when connection is closed cleanly """
    def connectionDone(self):
        pass
    
    
    """ 
        Called when connection is lost unexpectedly. 
        Logs the disconnect and returns control to the factory.
    """
    def connectionLost(self,reason):
        self.log.log(cll.level.ERROR,reason.value)
    
    
    """ 
        Called when connection fails without connecting. 
        Logs the failure and returns control to the factory.
    """
    def connectionFailed(self,reason):
        self.log.log(cll.level.ERROR,reason.value)
        
    """
        Execute the hook functions defined for this functions'
        caller in the order they were added by their extensions.
    """
    def execute_hook(self,*args,**kwargs):
        methodname = kwargs.get('name')
        
        
        if not methodname:
            methodname = tools.called_by(1)
        else:
            del kwargs['name']

        try:

            if methodname in self.factory.hook:
               
                
                for ext in self.factory.hook[methodname]:
                    method = getattr(ext,methodname, None)
            
                    if method is not None:
                        # !!! TODO: This *MAY* need changing to allow
                        # !!! the method to run in a separate thread.
                     
                        method(*args,**kwargs)

                    else:
                        self.log.log(cll.level.ERROR,'Hook method %s in %s does not exist' % (methodname,ext))
                        
                return True
            else:
                return False
            
        except Exception, e:
            # Called method raised an uncaught exception, catch it here and 
            # Drop a traceback into the log (EWW)
            self.log.log(cll.level.ERROR,'Uncaught Exception during hook delegation: %s' % e.message)
            
            # !!! TODO: Find a better way to log tracebacks
            self.log.log(cll.level.DEBUG,traceback.format_exc())
            
            
            
            return False
            
            
    """
        Called when the LineReceiver receives a full line.
        Attempts to parse the message using parse_message(),
        and then hands the parsed variables off to 
        handle_command().
    """
    def lineReceived(self, line):
        
        self.log.log(cll.level.NET,'<< ' + line)
        try:
            prefix, cmd, args = self.parse_message(line)
        except ValueError, e:
            # ValueException will occur when parse_message() fails.
            pass
        else:
            self.handle_command(cmd,prefix,args)
    
    
    """
        Called by lineReceived(), this attempts to call
        a st_receive_<SANITIZED_CMDNAME> function in the
        current class to deal with it specifically. If it
        cannot find a specific class, it calls a default
        cannot find a specific class, it calls a default
        st_receive_unknown() which logs the unknown command.
    """
    def handle_command(self, cmd, prefix, args):
    
        # Make sure that command is a string and lowercase
        # to avoid faggotry with poor formatting / numeric
        # commands.
        cmd = str(cmd).lower()
        
        # Check to see if class has a correctly named method 
        # for this command.
        
        try:
                method = getattr(self, "st_receive_%s" % cmd, None)
        
                if method is not None:
                    
                    # !!! TODO: This *MAY* need changing to allow
                    # !!! the method to run in a separate thread.
                    _v = method(prefix, args)
                    
                        
                else:
                    # Default to the st_receive_unknown method if
                    # a class was not found.
                    self.st_receive_unknown(prefix, cmd, args)
                
        except Exception, e:
            # Called method raised an uncaught exception, catch it here and 
            # Drop a traceback into the log (EWW)
            self.log.log(cll.level.ERROR,'Uncaught Exception during command delegation: %s' % e.message)
            
            # !!! TODO: Find a better way to log tracebacks
            self.log.log(cll.level.DEBUG,traceback.format_exc())
            
            self.quit()


    """
        Parses a protocol message in accordance with 
        the Spanning Tree 1.2.x specs and returns a list 
        containing prefix, command and arguments. Both
        undirected (COMMAND ARGUMENT ARGUMENT :TRAILING) and
        directed (:SOURCE COMMAND ARGUMENT ARGUMENT :TRAILING)
        messages are parsed correctly.
    """
    def parse_message(self,s):
        # If line is empty, log it as debug and do
        # not continue.
        if not s:
            self.log.log(cll.level.VERBOSE,'Encountered empty line while parsing, ignored.')
            raise ValueError('Encountered empty line while parsing')
            
        prefix = ''
        trailing = []

        # If first character is a colon, the command is directed.
        # Remove the colon and split the prefix and the rest of the
        # message on a space.
        if s[0] == ':':
            prefix,s = s[1:].split(' ',1)
        
        # Find the start of trailing data. If it exists,
        # split it off and then split the arguments.
        # Append the trailing data as an argument.
        # If it does not exist, simply split the arguments.
        if s.find(' :') != -1:
            s, trailing = s.split(' :',1)
            args = s.split()
            args.append(trailing) 
        else:
            args = s.split()
            
        # Pop the first item of the arguments off as
        # the command to be parsed.
        cmd = args.pop(0)
        
        return prefix, cmd, args


    """ 
        Called when the server returns an ERROR command.
        Logs the error and attempts to quit the application.
    """
    def st_receive_error(self,prefix,args):
        self.execute_hook(prefix,args)
        self.log.log(cll.level.ERROR,'Received ERROR response: %s' % args[0])
        return True
        
    """
        This method sends an ERROR command reply at the behest
        of reception methods.
    """
    def st_send_error(self,message):
        self.st_send_command('ERROR',None,None,message)
        
        
        
    """ 
        Called when the server returns an unknown command
        type (no st_receive_<SANITIZED_CMDNAME> in this 
        class). Logs the command.
    """
    def st_receive_unknown(self, prefix, cmd, args):
        self.execute_hook(prefix,cmd,args)
        self.log.log(cll.level.DEBUG,'Unknown command %s received' % cmd)
        return True
    
    def st_receive_nick(self,*args,**kwargs):
        self.execute_hook(*args,**kwargs)
        
    """
        This method is called when required to ping the peer server.
        This could be automatic (on a timeout) or manually when it is 
        necessary to check the server-server connection.
        Once a ping is sent, the reset_disconnect() method is called 
        to set a timeout on the PONG response, eventually trying to 
        reconnect if a response is not received in time.
    """
    def st_send_ping(self):
        self.log.log(cll.level.VERBOSE,'Initiating a PING request, setting up timer countdown till disconnect / retry')
        
        # Send using our server_sid (OUR OWN UID) and to the peer's UID.
        self.st_send_command('PING',[self.factory.cfg.server.sid,self.lookup_peer().uid],self.factory.cfg.server.sid)
        self.reset_disconnect()
    
    
    """
        This method is called when we receive a PONG command.
        If the PONG arguments are correct, we cancel any disconnect
        timeout pending and reset the ping timeout back to its'
        default.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/PING
    """
    def st_receive_pong(self,prefix,args):
        if args == [self.lookup_peer().uid,self.factory.cfg.server.sid]:
            self.log.log(cll.level.VERBOSE,'Received PONG, cancelling timeout call')
            self.reset_ping_timeout()
            if not self.factory.timeout.cancelled:
                self.factory.timeout.cancel()
            
        else:
            self.log.log(cll.level.VERBOSE,'Received PONG but values were incorrect, ignoring')
            
        return True
    
    """
        This method is called when a peer / remote server sends us a PING.
        It reverses the arguments and bounces a PONG back to the peer server.
        It also resets the ping timeout back to its' default.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/PING
    """
    def st_receive_ping(self,prefix,args):
        
        
        # Reverse the args to respond correctly to a ping.
        args.reverse()
        self.st_send_command('PONG',args,self.factory.cfg.server.sid)
        self.log.log(cll.level.VERBOSE,'Received PING, sending PONG and resetting time till initiating ping')
        self.reset_ping_timeout()
    
        return True
    
    """
        When called, this method cancels any active ping timeout counter 
        and creates a new timeout (calls st_send_ping() when the specified
        period is over).
    """
    def reset_ping_timeout(self):
        try:
            if self.factory.cfg.ping.initiate_after:
                if not self.factory.pingtimeout.cancelled:
                    self.factory.pingtimeout.cancel()
        except:
            pass
            
        self.factory.pingtimeout = reactor.callLater(self.factory.cfg.ping.initiate_after,self.st_send_ping)
        
        
    """
        When called, this method cancels any active disconnect timeout counter 
        and creates a new timeout. This forcefully reconnects the connection 
        when the specified period is over. This function is not used very much
        because usually we want to simply cancel the disconnect timeout (unlike
        ping timeout), without creating a new one straight after.
    """
    def reset_disconnect(self):
        try:
            if self.factory.cfg.ping.timeout_after:
                if not self.factory.pingtimeout.cancelled:
                    self.factory.pingtimeout.cancel()
        except:
            pass
            
        self.factory.timeout = reactor.callLater(self.factory.cfg.ping.timeout_after,self.transport.loseConnection)
    

    """
        This command builds and sends the CAPAB commands at the beginning
        of a connection phase. Also sends the pre-generated CHALLENGE 
        string for HMAC authentication.
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/CAPAB
    """
    def st_send_capab(self):
        self.log.log(cll.level.DEBUG,'Negotiating CAPAB')
        self.st_send_command('CAPAB','START')
        self.st_send_command('CAPAB',['MODULES',' '.join(self.factory.modules)])
        #Join all capabilities as NAME=VALUE separated by a space
        self.st_send_command('CAPAB','CAPABILITIES',None,' '.join(('%s=%s' % (key.upper(),value) for key,value in self.factory.capabilities.iteritems())))
        self.st_send_command('CAPAB','END')
        
        
    """
        This command receives and parses incoming CAPAB lines.
            START: 	We (re)initialize variables to hold peer
                    capabilities and modules since they may
                    have changed since last time.
            
            MODULES: We lowercase the list of modules just to
                    be sure, then split it on comma and extend
                    the list in factory.peer_modules.
            
            CAPABILITIES: We split the list of capabilities
                    on spaces, then split those key=value
                    pairs on =, creating a dict to update 
                    factory.peer_capabilities.
            
            END:	We show debug on the noted mods /
                    capabilities, and then call 
                    callback_connect_capab_end() to process
                    any CAPAB specific requirements.
                        
            UNDEFINED: We log that an undefined CAPAB command
                    was received, but nothing else.
                    
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/CAPAB
    """
    def st_receive_capab(self,prefix,args):
        if args[0] == 'START':
            self.factory.peer_capabilities = {}
            self.factory.peer_modules = []
            
        elif args[0] == 'MODULES':
            self.factory.peer_modules.extend(args[1].lower().split(','))
            
        elif args[0] == 'CAPABILITIES':
            self.factory.peer_capabilities.update(dict([pair.split('=') for pair in args[1].split(' ')])) 
            
        elif args[0] == 'END':
            self.log.log(cll.level.INFO,'Finished parsing peer CAPAB records')
            self.log.log(cll.level.VERBOSE,'Peer Modules: %s' % self.factory.peer_modules)
            self.log.log(cll.level.VERBOSE,'Peer Capabilities: %s' % self.factory.peer_capabilities)
            self.callback_connect_capab_end()
            
        else:
            self.log.log(cll.level.ERROR,"CAPAB Section '%s' invalid" % args[0])
            return False
        
        return True
        
        
    """
        Called when the initial capabilities negotiation
        is finished. Verifies if remote server is using the 
        correct protocol version and calls st_send_server()
        to continue with the connection process.
    """
    def callback_connect_capab_end(self):
        if int(self.factory.peer_capabilities.get('PROTOCOL')) != self.factory.cfg.peer_server.protocol:
            self.log.log(cll.level.ERROR,'Peer returned invalid or no protocol capability (we require %s).' % self.factory.cfg.peer_server.protocol)  
            self.st_send_error('I have no support for your protocol! :|')
            self.quit()
        else:
        
            # Parse CHANMODES
            cmode_types = self.factory.chanmodes
            cmode_types['A'],cmode_types['B'],cmode_types['C'],cmode_types['D'] = self.factory.peer_capabilities.get('CHANMODES').split(',')
            
            # Parse USERMODES
            umode_types = self.factory.usermodes	
            umode_types['A'],umode_types['B'],umode_types['C'],umode_types['D'] = self.factory.peer_capabilities.get('USERMODES').split(',')
            
            # Parse PREFIX	
            try:
                self.factory.prefix = re.search('^(?i)\((?P<mode>[a-z]*)\)(?P<prefix>.*)$',self.factory.peer_capabilities.get('PREFIX')).group('mode')
            except KeyError:
                self.log.log(cll.level.ERROR,'Could not parse CAPAB PREFIX=!')
                self.quit()
            
            
            self.log.log(cll.level.DEBUG, 'Capabilities successfully negotiated')
            self.st_send_server()	

            
    """
        Generates and sends the local server details, including
        HMAC details from st_negotiate_hmac() if a CAPAB challenge
        was received.
    """
    def st_send_server(self):
        self.log.log(cll.level.INFO,'Sending our local server details')
        self.st_send_command('SERVER',[self.factory.cfg.server.name,self.st_negotiate_hmac(),0,self.factory.cfg.server.sid],None,self.factory.cfg.server.description)

        
    """ 
        Receives server line, parsing its' arguments into 
        a dictionary using cmd_types.sr_assoc().
        
        Once the line has been parsed, this attempts to 
        look up the server UID and either updates the Server
        object if it does, or creates a new one and registers it
        in the UID dictionary.
    
        It then checks to see if this is the peer server
        record sent during a connection attempt and if so, it
        stores the UID of our peer server in factory.peer_uid.
        
        Finally, if this is the peer server record it calls
        callback_connect_server_end() which continues with the
        connection process.
    """
    def st_receive_server(self,prefix,args):
        
        self.log.log(cll.level.INFO,'Receiving remote server details')
        

        # Turn the list of fields and arguments into a keyed dictionary
        # Or quit if arguments can't be keyed
        try:
            _sr = sr_assoc(cmd.SERVER,args)
            
        except ValueError:
            self.log.log(cll.level.ERROR,'SERVER command returned wrong number of arguments.')
            self.st_send_error('SERVER command returned wrong number of arguments.')
            self.quit()
            return False
        
        

        # Check to see if the server exists so we can modify it if it does.
        server = self.lookup_uid(_sr.get('uid'))
        
        # Otherwise create a new server object
        if not server:
            server = uid.Server(_sr.get('uid'))
            
        # Set attributes of server object using the variable names / values
        # from _sr
        server.update_from(_sr)

        self.execute_hook(server=server)
        # Attempt to add the server to the UID dict (this will log an error on 
        # update since it already exists, but is not an issue).
        self.add_uid(server)
            
        # If password argument is not an asterisk, the server is a peer and 
        # being added during connect, so save its' uid as factory.peer_uid
        # for use in lookup_peer.
        if _sr.get('password','*') != '*':
            self.factory.peer_uid = _sr.get('uid')
            self.callback_connect_server_end()
        else:
            self.callback_server_end()
    
        return True
        
        
    """
        This is a special callback method used when the first
        SERVER command is sent by the peer server, identifying
        itself. This occurs during the connect process.
        This method checks to make sure the server details returned
        are sane, and then attempts to authenticate its' details
        with our locally held ones using st_authenticate().
        If details are valid, we initiate the last part of the
        connection negotiation, bursting data with st_send_burst().
    """
    def callback_connect_server_end(self):
        # Return the peer object for some sanity checks.
        peer = self.lookup_peer()
        
        # The peer server should never be more than 0 hops away.
        if int(peer.hops) != 0:
            self.log.log(cll.level.ERROR,'SERVER connected is not 0 hops away, :wtc:')
            self.st_send_error('SERVER returned an invalid hop count for a peer server.')
            self.quit()
            return

        if self.st_authenticate():
            self.log.log(cll.level.INFO,'Remote server name / password authenticated')
            self.st_send_burst()
        else:
            self.log.log(cll.level.ERROR,'Remote server name / password NOT AUTHENTICATED')
            self.st_send_error('Invalid credentials')
            self.quit()
    
    
    """ 
        Called after a server is added by SERVER, but which is
        *NOT* the initial (peer) server added during the connection
        process.
    """
    def callback_server_end(self):	
        pass
        
        
    """
        Initiates a local-to-remote network BURST which updates
        the peer server / network on the status of OUR connected
        clients, pseudoclients, metadata, channels and opers.
    """
    def st_send_burst(self):
        self.log.log(cll.level.INFO,'Attempting outbound network burst')
        self.st_send_command('BURST',int(time.time()), self.factory.cfg.server.sid)
        self.st_send_command('VERSION',None, self.factory.cfg.server.name,self.factory.server_version)

        self.execute_hook()
        
        for handler,user in self.factory.pseudoclients.values():
            # We have to parse the modes here rather than in st_add_pseudoclient because
            # we do not know which modes the peer server will accept until after the 
            # CAPAB phase of connection negotiation.
            _modes,_params = user.unparsed_modes
            user.modes = self.seperate_modes(_modes,_params,user)
            
            self.st_send_uid_from_user(user)
            
        self.st_send_command('ENDBURST','', self.factory.cfg.server.sid)
        self.log.log(cll.level.INFO,'Outbound network burst completed')
    
    """
        Sends a fake UID command to introduce a pseudoclient to the network.
        Also creates and adds a User() UID for this client to our UID list.
    """	
    def st_add_pseudoclient(self,nick,host,ident,modes,gecos,client_handler):
        _t = int(time.time())
        
        try:
            _modes, _params = modes.split(' ')
        except ValueError:
            _modes = modes
            _params = ''
        
        _uid = tools.UIDGenerator.generate()
        _user = uid.User(_uid)
        _user.nick = nick
        _user.hostname = 'localhost'
        _user.displayed_hostname = host
        _user.ident = ident
        _user.ip = '127.0.0.1'
        _user.signed_on = _t
        _user.unparsed_modes = (_modes,_params)
        
        _user.gecos = gecos
        
        self.add_uid(_user)
    
        self.factory.pseudoclients[_uid] = (client_handler,_user)
        
        return _user
    
    """
        This command is called to add a (real or fake) user to peers
        by generating a UID command from a given User() item
    """
    def st_send_uid_from_user(self,user):
        _t = int(time.time())
        _modes, _params = user.modes_return_parsed()
        self.st_send_command('UID',[user.uid,_t,user.nick,user.hostname,user.displayed_hostname,user.ident,user.ip,user.signed_on,_modes,_params], self.factory.cfg.server.sid, user.gecos)
    
    
    """
        Called when we receive a BURST command from our peer,
        this signifies that we are about to receive burst data.
        We make sure that a server object is initialized and added
        to the UID dict before the BURST so its' data can be added
        simply.
        Finally we set is_bursting to true to allow subsequent BURST
        data to modify local data.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/BURST
        
    """
    def st_receive_burst(self,prefix,args):
        self.log.log(cll.level.INFO,'Receiving inbound network burst')
        if not self.lookup_uid(prefix,allow_peer=True):
            server = uid.Server(prefix)
            self.add_uid(server)
        
        self.factory.is_bursting = True
        
        return True
        
        
    """
        Called when we receive a network burst VERSION
        command, this sets the version of the specified
        server.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/VERSION
        
    """
    def st_receive_version(self,prefix,args):
    
            server = self.lookup_uid(prefix,allow_peer=True)
            server.version = ''.join(args).split(' :')
    
            self.execute_hook(version=server.version)
            return True
    
    
    """
        Called when we receive a network burst UID
        command, this creates / updates a User 
        instance with the given data.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/UID
        
    """
    def st_receive_uid(self,prefix,args):
            
            # Turn the list of fields and arguments into a keyed dictionary
            try:
                _sr = sr_assoc(cmd.UID,args,ignore_reduce=True)
            except ValueError:
                self.log.log(cll.level.ERROR,'UID command returned wrong number of arguments.')
                self.st_send_error('UID command returned wrong number of arguments.')
                return False
                
            
            
            # Check to see if the user exists so we can modify it if it does.
            user = self.lookup_uid(_sr.get('uid'))
            
            # Otherwise create a new user object
            if not user:
                user = uid.User(_sr.get('uid'))
            
            # Convert parseable modes / parameters into a list ready for
            # setting on a specific target, then fix the variables in _sr
            # ready for Unique.update_from()
            _mvars = self.seperate_modes(_sr.get('modes'),_sr.get('parameters'),user)				
            _sr['modes'] = _mvars
            del _sr['parameters']
            
            # Set attributes of user object using the variable names / values
            # from _sr			
            user.update_from(_sr)
            
            if not 'r' in user.modes:
                # !!! TODO: Send FMODE here to update the user with a +r mode which allows it to make channels. Maybe
                pass
                
            self.execute_hook(user=user)
            
            # Attempt to add the server to the UID dict (this will log an error on 
            # update since it already exists, but is not an issue).
            self.add_uid(user)
        
            return True
        
    """
        Called when we receive a network burst OPERTYPE
        command, this updates a User instance 
        with the OPERTYPE value.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/OPERTYPE
        
    """		
    def st_receive_opertype(self,prefix,args):
    
            user = self.lookup_uid(prefix)
            
            if not user:
                self.log.log(cll.level.ERROR,'We cant set an oper type on a UID which does not exist!')
                return False
            
            try:
                _sr = sr_assoc(cmd.OPERTYPE,args)
            except ValueError:
                self.log.log(cll.level.ERROR,'OPERTYPE command returned wrong number of arguments.')
                self.st_send_error('OPERTYPE command returned wrong number of arguments.')
                return False
                
            user.oper_type = _sr['type']
            
            self.execute_hook(user=user)
            
            return True
            
        
    """
        Called when we receive a network burst METADATA
        command, this updates a User instance 
        with the METADATA value.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/METADATA
        
    """		
    def st_receive_metadata(self,prefix,args):

        # Turn the list of fields and arguments into a keyed dictionary
        try:
            _sr = sr_assoc(cmd.METADATA,args)
        except ValueError:
            self.log.log(cll.level.ERROR,'METADATA command returned wrong number of arguments.')
            self.st_send_error('METADATA command returned wrong number of arguments.')
            return False
            
        unique = self.lookup_uid(_sr.get('uid'))
        
        if not unique:
            self.log.log(cll.level.ERROR,"Could not find the Unique() '%s' to add METADATA" % _sr.get('uid'))
            return False
        
        unique.metadata[_sr.get('name')] = _sr.get('value')
        
        self.execute_hook(unique=unique)
        return True
        
    
    """
        Called when we receive a FJOIN
        command, this creates / updates a Channel()
        UID while also linking it to the User()'s in
        it.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/FJOIN
        
    """		
    def st_receive_fjoin(self,prefix,args):
        _t = int(time.time())
        
    
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            _sr = sr_assoc(cmd.FJOIN,args,ignore_reduce=True,reduce_gecos=False)

        except ValueError:
            self.log.log(cll.level.ERROR,'FJOIN command returned wrong number of arguments.')
            self.st_send_error('FJOIN command returned wrong number of arguments.')
            return False
            
        # Check to see if the channel exists so we can modify it if it does.
        channel = self.lookup_uid(_sr.get('channel'))
        
        # Otherwise create a new channel object
        if not channel:
            channel = uid.Channel(_sr.get('channel'))			
        
        # We have to handle the users argument manually because it has
        # a strange format. We turn it into a list of tuples containing
        # a UUID and a list of modes that user has on the channel.
        try:
            _sr['users'] = dict([reversed(v.split(',')) for v in _sr.get('users').split(' ')])
        except ValueError:
            # No users in this FJOIN
            _sr['users'] = {}
        
        if _t > _sr['timestamp']:
            del channel.modes

        _modes = self.seperate_modes(_sr.get('modes'),_sr.get('parameters'),channel)
        del _sr['parameters']
        _sr['modes'] = _modes
        
        # We iterate over the list of users, looking up each user instance
        # in turn, and linking each user to the channel, and the channel to
        # each user.
        for uuid, modes in _sr['users'].iteritems():
            _user = self.lookup_uid(uuid)
            
            if _user:
                _user.channels[channel.uid] = channel
                _sr['users'][uuid] = {'instance': _user,'modes': list(modes)}
            
        # Set attributes of channel object using the variable names / values
        # from _sr
        
        channel.update_from(_sr)
        
        self.add_uid(channel)
            
        self.execute_hook(**_sr)
        
        return True
        
    
    """
        Called when we receive a FHOST
        command, this updates a User()
        UID with the correct host.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/FHOST
        
    """		
    def st_receive_fhost(self,prefix,args):
    
            user = self.lookup_uid(prefix)
            
            if not user:
                self.log.log(cll.level.ERROR,'We cant set an oper type on a UID which does not exist!')
                return False
            
            try:
                _sr = sr_assoc(cmd.FHOST,args)
            except ValueError:
                self.log.log(cll.level.ERROR,'FHOST command returned wrong number of arguments.')
                self.st_send_error('FHOST command returned wrong number of arguments.')
                return False
                
            user.displayed_hostname = _sr['hostname']
            
            self.execute_hook(user=user)
            
            return True
        
        
        
    """
        Called when we receive a FMODE
        command, this updates a Channel()
        or User() UID with the correct modes.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/FMODE
        
    """		
    def st_receive_fmode(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:

            _sr = sr_assoc(cmd.FMODE,args,ignore_reduce=True,)
        except ValueError:
            self.log.log(cll.level.ERROR,'FMODE command returned wrong number of arguments.')
            self.st_send_error('FMODE command returned wrong number of arguments.')
            return False
        
        # Check to see if the target exists so we can modify it if it does.
        target = self.lookup_uid(_sr.get('target'))
        del _sr['target']
        
  
        _modes = self.seperate_modes(_sr.get('modes'),_sr.get('parameters'),target)
        del _sr['parameters']
        _sr['modes'] = _modes
            

        #If target is a server, don't bother for the time being
        if isinstance(target,uid.Server):
            return True
            
        
        target.update_from(_sr)
        
        self.execute_hook(prefix, channel=target,**_sr)
        
        return True
    
    
    """
        Called when we receive a MODE
        command, this updates a Channel()
        or User() UID with the correct modes.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/MODE
        
    """		
    def st_receive_mode(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            
            _sr = sr_assoc(cmd.MODE,args,ignore_reduce=True,reduce_gecos=True)
        except ValueError:
            self.log.log(cll.level.ERROR,'MODE command returned wrong number of arguments.')
            self.st_send_error('MODE command returned wrong number of arguments.')
            return False
        
        # Check to see if the target exists so we can modify it if it does.
        target = self.lookup_uid(_sr.get('target'))
        
        del _sr['target']
        
        if target:
            _modes = self.seperate_modes(_sr.get('modes'),_sr.get('parameters'),target)
            del _sr['parameters']
            _sr['modes'] = _modes
                
            #If target is a server, don't bother for the time being
            if isinstance(target,uid.Server):
                return True
                
            target.update_from(_sr)
            
            self.execute_hook(source_uid=prefix,target=target)
            
            return True
        
        
    """
        Called when we receive a PART
        command, this removes a user from
        a Channel().
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/PART
        
    """		
    def st_receive_part(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            
            _sr = sr_assoc(cmd.PART,args,ignore_reduce=True,reduce_gecos=True)
        except ValueError:
            self.log.log(cll.level.ERROR,'PART command returned wrong number of arguments.')
            self.st_send_error('PART command returned wrong number of arguments.')
            return False
        
        # Check to see if the user exists so we can modify it if it does.
        user = self.lookup_uid(prefix)
        
        if user:
            channel = self.lookup_uid(_sr.get('channel'))

            if channel:
                self.execute_hook(user=user,channel=channel)
                
               
                self.log.log(cll.level.VERBOSE,'PART: Removed user %s from %s ' % (user.uid,channel.uid))
                del channel.users[user.uid]
        
        return True
        
    """
        Called when we receive a KICK
        command, this removes a user from
        a Channel().
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/KICK
        
    """		
    def st_receive_kick(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            
            _sr = sr_assoc(cmd.KICK,args,ignore_reduce=True,reduce_gecos=True)
        except ValueError:
            self.log.log(cll.level.ERROR,'KICK command returned wrong number of arguments.')
            self.st_send_error('KICK command returned wrong number of arguments.')
            return False
        
        # Check to see if the kicked user exists so we can modify it if it does.
        user = self.lookup_uid(_sr.get('user'))
        
        channel = self.lookup_uid(_sr.get('channel'))

        self.execute_hook(user=user,channel=channel)
        
        self.log.log(cll.level.VERBOSE,'KICK: Removed user %s from %s ' % (user.uid,channel.uid))
        del channel.users[user.uid]
        
        return True
        
        
        
    """
        Called when we receive a QUIT
        command, this removes a user from
        our user lists.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/QUIT
        
    """		
    def st_receive_quit(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            
            _sr = sr_assoc(cmd.QUIT,args)
        except ValueError:
            self.log.log(cll.level.ERROR,'QUIT command returned wrong number of arguments.')
            self.st_send_error('QUIT command returned wrong number of arguments.')
            return False
        
        # Check to see if the user exists so we can modify it if it does.
        user = self.lookup_uid(prefix)
        
        self.execute_hook(user=user,reason=_sr.get('reason'))
        
        _i = 0
        for name, channel in user.channels.iteritems():
            
            if user.uid in channel.users:
                del channel.users[user.uid]
                _i += 1

        
        self.log.log(cll.level.DEBUG, 'QUIT: Removed user %s from %d channels' % (user.uid,_i))
        
        del self.factory.uid[prefix]
        self.log.log(cll.level.DEBUG, 'QUIT: Removed user %s from global UID dict' %(user.uid))
        
        del user
        
        return True
        
        
    """
        This is a relatively complex function which is designed
        to parse a modes / parameters set based on the data received
        from the peer server during CAPAB (USERMODES,CHANNELMODES,
        PREFIX). It will return a list of tuples (give,mode,param).
    """
    def seperate_modes(self,modes,parameters,target=None):
        _or = []
        _g = False
        parameters = parameters.split(' ')
        
        # Iterate over each character in the list of modes
        for c in modes:
        
            # If char is a modifier, set the current give / take status
            # and continue looping characters
            if c == '+':
                _g = True
            elif c == '-':
                _g = False
            else:
                # Otherwise look up the mode type
                _type = self.lookup_mode_type(c,target)
                
                # Type returned None, avoid setting any modes just in case.
                if not _type:
                    self.log.log(cll.level.ERROR,'Unknown mode %s encountered for target %s.' % (c,target))
                    return []
            
                # Check the mode type, consume a parameter if required
                if tools.contains_any('ABX',_type):
                    # Has parameter
                    _param = parameters.pop(0)
                elif tools.contains_any('C',_type) and _g:
                    # Has parameter when set
                    _param = parameters.pop(0)
                else:
                    # Has no parameters, set none
                    _param = None
                    
                # Attempt to look up the parameter as a UID, and replace it
                # with the given UID if it exists.
                _param_uid = self.lookup_uid(_param)
                
                if _param_uid:
                    _param = _param_uid
                
                # Append this mode to the modes-to-set list
                _or.append((_g,c,_param))
                
        return _or
                    
                    
    """
        Called when we receive a FTOPIC
        command, this updates a Channel()
        UID's topic attribute.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/FTOPIC
        
    """		
    def st_receive_ftopic(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            _sr = sr_assoc(cmd.FTOPIC,args)
        except ValueError:
            self.log.log(cll.level.ERROR,'FTOPIC command returned wrong number of arguments.')
            self.st_send_error('FTOPIC command returned wrong number of arguments.')
            return False
            
        # Check to see if the channel exists so we can modify it if it does.
        channel = self.lookup_uid(_sr.get('channel'))
        
        
        if not channel:
            self.log.log(cll.level.ERROR,'FTOPIC attempted on non existent channel %s.' % _sr.get('channel'))
            self.st_send_error('FTOPIC attempted on non existent channel.')
            return False
            
        if self.execute_hook(user=None,channel=channel,topic=_sr.get('topic')):
            channel.update_from(_sr)
        
        
        return True
        
        
    """
        Called when we receive a TOPIC
        command, this updates a Channel()
        UID's topic attribute.
        
        http://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/TOPIC
        
    """		
    def st_receive_topic(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            _sr = sr_assoc(cmd.TOPIC,args)
        except ValueError:
            self.log.log(cll.level.ERROR,'TOPIC command returned wrong number of arguments.')
            self.st_send_error('TOPIC command returned wrong number of arguments.')
            return False
            
        # Check to see if the channel exists so we can modify it if it does.
        channel = self.lookup_uid(_sr.get('channel'))
        user = self.lookup_uid(prefix)
       
        if not channel:
            self.log.log(cll.level.ERROR,'TOPIC attempted on non existent channel %s.' % _sr.get('channel'))
            self.st_send_error('TOPIC attempted on non existent channel.')
            return False
        
        if not user:
            self.log.log(cll.level.ERROR,'TOPIC change attempted by non existent user %s.' % prefix)
            self.st_send_error('TOPIC attempted by non existent user.')
            return False
            
        if self.execute_hook(user=user,channel=channel,topic=_sr.get('topic')):
            channel.update_from(_sr)
       
        return True
    
    """
        Called when we receive the ADDLINE command.
    """
    def st_receive_addline(self,prefix,args):
        self.execute_hook(prefix,args)
        return True
        
        
    """
        Called when we receive an ENDBURST notification,
        this indicates that a network burst is over.
        First we turn off factory.is_bursting to stop
        arbitrary commands from updating our local data,
        and then if this is a BURST during initial connection,
        we indicate that we are now connected.
        Finally, we reset all reconnection / ping timeouts and
        initiate an initial ping to the peer server (to start
        the ping-system going. If the peer server has a shorter
        ping interval, it will take over the PING - PONG requests,
        otherwise this end will handle them itself.
    """			
    def st_receive_endburst(self,prefix,args):
        self.log.log(cll.level.INFO,'Inbound network burst completed')
        if self.factory.is_bursting:
            def reset_burst():
                self.log.log(cll.level.INFO,'Burst finished')
                self.factory.is_bursting = False
                
            reactor.callLater(5,reset_burst)
            
            
            if not self.factory.connected:
                self.reset_ping_timeout()
                self.factory.connected = True
                self.st_send_ping()
                self.log.log(cll.level.INFO,'Servers synchronized & connected successfully')
                self.execute_hook(prefix,args)
        return True
    
    
        
    """
        Called when we receive a PRIVMSG, this should
        check to see if it is destined for one of our 
        pseudoclients and if so, hand it off to a pseudo
        client handler.
    """
    def st_receive_privmsg(self,prefix,args):
        # Turn the list of fields and arguments into a keyed dictionary
        try:
            _sr = sr_assoc(cmd.PRIVMSG,args)
        except ValueError:
            self.log.log(cll.level.ERROR,'PRIVMSG command returned wrong number of arguments.')
            self.st_send_error('PRIVMSG command returned wrong number of arguments.')
            return False
        

        if _sr.get('uid') in self.factory.pseudoclients:
            
            
            try:
                cprefix, _sr['message'] = _sr.get('message').split(' ',1)
            except ValueError:
                cprefix = _sr.get('message')
                _sr['message'] = ''
                
        
            
            if not self.execute_hook(name='ps_privmsg_%s' % (cprefix.lower()),source_uid=prefix,command=cprefix,message=_sr.get('message'),pseudoclient_uid=_sr.get('uid')):
                self.st_receive_privmsg_unknown(source=prefix,command=cprefix,message=_sr.get('message'),pseudoclient_uid=_sr.get('uid'))
        
        else:
            self.execute_hook(args=_sr)
            
        return True

    """
        Called when we receive a PRIVMSG to a valid pseudoclient 
        whos' handler did not contain a method for this command
        type. Replies with a generic "unknown command" message
    """
    def st_receive_privmsg_unknown(self,source,command,message,pseudoclient_uid):
            self.st_send_command('NOTICE',[source],pseudoclient_uid,'Command %s is not valid.' % command)
    
    
    
    """ 
        This builds a command from a set of arguments 
        and sends it to the peer.
        If cmddest is none, a 'directed' command is not sent.
    """
    def st_send_command(self,cmdname,cmdargs,cmddest=None,cmdtext=None):
        if cmddest is not None:
            _buffer = ':%(cmddest)s %(cmdname)s' % locals()
        else:
            _buffer = '%(cmdname)s' % locals()

        if cmdargs is not None:
            _buffer += ' %s' % ' '.join(self.to_sequence(cmdargs))
        
        if cmdtext is not None:
            _buffer = ' :'.join([_buffer,cmdtext])
            return self._sendLine(_buffer)
        else:
            return self._sendLine(_buffer)    
        

    def _sendLine(self,_buffer):
        self.log.log(cll.level.NET,'>> ' + _buffer)
        self.sendLine(_buffer)
        
    """
        This function attempts to use tools.hmac to generate
        a valid HMAC hash given the received peer CHALLENGE
        CAPAB. If we did not receive a CHALLENGE, it simply
        returns the cleartext password to be used in-place
        for authentication.
    """
    def st_negotiate_hmac(self):
        #If peer sent a HMAC challenge, calculate our HMAC
        _cmac = self.factory.peer_capabilities.get('CHALLENGE')
        if _cmac is None:
            self.log.log(cll.level.DEBUG, 'Peer did not send a HMAC challenge, falling back to plaintext')
            return self.factory.password
        
        self.log.log(cll.level.DEBUG, 'Peer sent a HMAC challenge, proceeding with HMAC generation')
        self.factory.use_hmac = True
        return tools.hmac(self.factory.cfg.peer_server.send_password,_cmac)
        

    """
        Called when we receive a SERVER response from the peer, this
        function attempts to validate the peers credentials, either 
        using HMAC via tools.hmac or with plaintext password 
        authentication if HMAC is not available.
    """
    def st_authenticate(self):
        _peer = self.lookup_peer()
        
        
        if not self.factory.use_hmac:
            self.log.log(cll.level.DEBUG, 'HMAC is disabled, checking remote credentials via plaintext')
            return _peer.password == self.factory.cfg.peer_server.rcv_password
        
        self.log.log(cll.level.DEBUG, 'HMAC is enabled, checking remote credentials via HMAC')
        return _peer.password == tools.hmac(self.factory.cfg.peer_server.rcv_password,self.factory.capabilities.get('CHALLENGE'))
        
        
    """ 
        This function looks up a UID in the factory.uid dictionary.
        If allow_peer is false (the default), then it raises an exception
        when one attempts to look up the peer_uid. This is to stop the peer_uid
        from being looked up accidentally when a non-peer-server or user lookup
        was the intended functionality (e.g. attempting to lookup a user using 
        prefix instead of args[0]).
        Returns the requested Unique() object or nothing.
    """
    def lookup_uid(self,i_uid,allow_peer=True):
        if self.factory.peer_uid == i_uid and not allow_peer:
            raise UserWarning('YOU MUST USE LOOKUP_PEER TO RETRIEVE THE PEER SERVER INFO (%s)' % (i_uid))

        return self.factory.uid.get(i_uid)

            
    """ 
        This function looks up the peer uid Server() in the
        factory.uid dictionary. If it does not exist (:wtc:)
        then it forces the application to exit.
    """
    def lookup_peer(self):
        _p = self.factory.uid.get(self.factory.peer_uid)
        
        if _p:
            return _p
            
        raise KeyError('Server saved as Peer (%s) does not exist in server UID list!' % self.factory.peer_uid)
        self.log.log(cll.level.ERROR,'Server saved as Peer (%s) does not exist in server UID list!' % self.factory.peer_uid)
        self.quit()
        
        
    """
        This function attempts to add a Unique() instance
        to the factory.uid dictionary. If the UID already
        exists in the dictionary it is not re-added, but
        a debug message is logged.
    """
    def add_uid(self,i_uid):
        if isinstance(i_uid,uid.Unique):
            if i_uid.uid not in self.factory.uid:
                self.factory.uid[i_uid.uid] = i_uid
            else:
                self.log.log(cll.level.DEBUG, "Tried to record UID %s which already exists (THIS IS NATURAL WHEN A RECORD IS UPDATED)" % (i_uid.uid))
        else:
            raise TypeError("Tried to record UID with an invalid type of %s" % (i_uid.__class__))
            self.log.log(cll.level.ERROR,"Tried to record UID with an invalid type of %s" % (i_uid.__class__))

    
    def lookup_mode_type(self,mode,target=None):
        if (target and isinstance(target,uid.Channel)) or not target:
            v = ''.join([key for key,value in self.factory.chanmodes.iteritems() if mode in value])
        
            if v:
                return v
        
            if mode in self.factory.prefix:
                return 'X'
        
        if (target and isinstance(target,uid.User)) or not target:
            return ''.join([key for key,value in self.factory.usermodes.iteritems() if mode in value])
        else:
            return ''
            
        
        
    """
        Converts all iterable sequences to the correct
        representation while keeping strings as atomic.
    """
    def to_sequence(self,arg):
        def _multiple(x):  
            return hasattr(x,"__iter__")
        if _multiple(arg):  
            return [str(a) for a in arg]
        else:
            return (str(arg),)
        