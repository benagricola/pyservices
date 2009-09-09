"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

from datetime import datetime as datetime

import common.log_levels as cll
import common.tools as tools
import common.ext as ext
from pprint import pprint, pformat

from twisted.enterprise import adbapi 
from twisted.internet import reactor
from twisted.internet import defer

"""
    Acts as a container for extension functions which
    hook into the command delegation process.
"""
class SQLLiveEnforcer(ext.BaseExtension):
    required_extensions = ['SQLLiveExtension']
    
    def __init__(self,*args,**kwargs):
        super(self.__class__, self).__init__(*args,**kwargs)
    
        self.sqe = self.factory.loaded_extensions.get('SQLLiveExtension')
        

        # Check to see if a UID for enforcer has already been created.
        # If not, create it, otherwise don't create another one because this
        # extension has just been reloaded.
        if not hasattr(self.factory,'enforcer') or not self.factory.enforcer:
            self.create_enforcer()

        #cfg_oper_tool = self.factory.cfg.sqlextension.services.oper_tool
        #self.oper_tool = self.protocol.st_add_pseudoclient(cfg_oper_tool.nick,cfg_oper_tool.host,cfg_oper_tool.ident,'+iow',cfg_oper_tool.realname,self,'oper')
        
   
    """
        Calls the factory method to create a pseudoclient for this
        extension. This pseudoclient will be added as a UID during
        our outbound network BURST on connect, creating a fake 
        client which we can receive commands for.
    """  
    def create_enforcer(self):
        cfg_enforcer = self.factory.cfg.sqlextension.services.enforcer
        self.factory.enforcer = self.protocol.st_add_pseudoclient(cfg_enforcer.nick,cfg_enforcer.host,cfg_enforcer.ident,'+iow',cfg_enforcer.realname,self)
     
     
    """ 
        This method is called when a runOperation callback
        is required. All it does is debug log that the 
        query completed successfully.
    """
    def query_update_callback(self,*args,**kwargs):
        self.log.log(cll.level.DATABASE,'Query OK')
        return True
    
    
    """ 
        This method is called when an SQL query returns an
        error. It logs the error and then attempts to 
        exit the application via the receivers' quit() method.
    """
    def query_error_callback(self,error):
        self.log.log(cll.level.DATABASE,'Query encountered error: %s' % error.value)
        return True
        
        
    """
        Called on a timeout after a ban, this
        function unbans a given banmask on a 
        channel using the enforcer UID set 
        during net burst.
    """
    def do_unban(self,*args,**kwargs):
        channel = kwargs.get('channel')
        banmask = kwargs.get('banmask')

        self.protocol.st_send_command('SVSMODE',[channel.uid,'-b',banmask],self.factory.enforcer.uid)
        self.log.log(cll.level.DEBUG,'Unbanned %s on %s (Timeban Expiry)' % (banmask,channel.uid))
        
        
    """
        This function enforces modes for a specific user
        on a specific channel using either their global
        access level or their access level on that channel,
        depending on the channel type.
    """
    
    def enforce_modes(self,user,db_user,channel,db_channel,db_accesslist):
        cfg_enforcer = self.factory.cfg.sqlextension.services.enforcer

        # Grab ID / founder ID like this instead of using .get()
        # so in the (most likely impossible) event that neither a
        # user or db record is found at this point, a user is not 
        # given maximum access by mistake (the services will crash)
        
        
        public = db_channel['type'].startswith('PUBLIC')
        
        if not db_user:
            effective_level = 0
            
        elif db_user['id'] == db_channel['founder_id']:
            effective_level = 100

        elif db_channel['type'] in ('ACCESSLIST','PUBLIC_ACCESSLIST'): 
            
            effective_level = db_accesslist.get(db_user['id'],0)
                  
        else:
             effective_level = db_user['level']
        
       
        # First check if users' level is equal or more
        # than the minimum level for this channel, otherwise
        # remove them if the channel is not public
        if effective_level < db_channel['min_level'] and not public:
        
            banmask = '*!*@%s' % user.displayed_hostname
            
            self.protocol.st_send_command('SVSMODE',[channel.uid,'-o+b',user.uid,banmask],self.factory.enforcer.uid)
            self.protocol.st_send_command('SVSPART',[user.uid,channel.uid],self.factory.enforcer.uid)
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Access to %s denied by user level (%s < %s). You have been banned for %ss' % (channel.uid,effective_level,db_channel['min_level'],cfg_enforcer.ban_accessdenied_expiry))
            
            reactor.callLater(cfg_enforcer.ban_accessdenied_expiry, self.do_unban,channel=channel,banmask=banmask)
            
            self.log.log(cll.level.DEBUG,'Banned %s on %s (%ss Access denied timeban)' % (banmask,channel.uid,cfg_enforcer.ban_accessdenied_expiry))
            return

        give_user = ''
        take_user = ''
        
        modes_order = 'qaohv'
        give = ''
        take = ''
        if not db_user:
            # Remove everything, this user doesn't exist
            take = modes_order
            
        elif db_user.get('id') == db_channel['founder_id']:
            # Remove nothing, user is the channel founder
            # so give founder mode + all trimmings 
            give = modes_order
            
        elif effective_level >= db_channel['level_superop']:
            # Remove nothing, superops are awesome.
            # Give them all roles up to superop
            give = modes_order[1:]
            take = modes_order[0]
            
        elif effective_level >= db_channel['level_op']:
            # Remove superops only (no-one should ever have this)
            # because SOP is given by services only
            give = modes_order[2:]
            take = modes_order[:2]

            
        elif effective_level >= db_channel['level_halfop']:
            # Remove ops
            give = modes_order[3:]
            take = modes_order[:3]

            
        elif effective_level >= db_channel['level_voice']:
            # Remove halfops
            give = modes_order[4:]
            take = modes_order[:4]
        else:
            # Remove everything
            take = modes_order
        
        if give:
            give = '+' + give
            give_user = user.uid
            
        if take:
            take = '-' + take
            take_user = user.uid
        
        # Send the mode change
        self.protocol.st_send_command('SVSMODE',[channel.uid,give + take,give_user,take_user],self.factory.enforcer.uid)
        
        
    @defer.inlineCallbacks
    def access_level_pass(self,*args,**kwargs):
        users = kwargs.get('users')
        channel = kwargs.get('channel')

        if not channel or not users:
            return 

        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
        db_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,channel.uid)
        
        if not db_channel:
            # Channel is not registered, ignore it
            return
        
        # Get all users at once so not to spam queries
        user_nicks = [user['instance'].nick for user in users.values()]
        
        db_users = yield self.factory.db.runInteraction(self.sqe.get_users_complete,user_nicks)
        
        for uitem in users.values():
            user = uitem.get('instance')
            modes = uitem.get('modes')
            
            db_user = db_users.get(user.nick,None)
            self.enforce_modes(user,db_user,channel,db_channel,db_accesslist)
                

    """
        This command is hooked when someone joins a channel.
        If the channel is still pending an update via database,
        we add a callback to the database update and return.
        Otherwise, we execute an access level pass over the 
        channel.
    """
    @defer.inlineCallbacks
    def st_receive_fjoin(self,timestamp,channel,users,modes):

        channel_uid = self.protocol.lookup_uid(channel)
        
        if not channel_uid:
            self.log.log(cll.level.ERROR,'We received a hook FJOIN but the channel could not be looked up by UID :wtc:')

        elif self.factory.is_bursting:
            self.access_level_pass(users=channel_uid.users,channel=channel_uid)
        else:
            
            db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel_uid.uid)
            db_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,channel_uid.uid)
        
            for user in users:
                user_uid = self.protocol.lookup_uid(user)
                if not user_uid:
                    break
                db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user_uid.nick)
                self.enforce_modes(user_uid,db_user,channel_uid,db_channel,db_accesslist)
        

        
    """
        This is called when we receive a new UID from the peer server,
        either during the connect sequence or when a new client is 
        introduced. If the user lookup is still pending, we add a
        callback on the query and return, otherwise we trigger
        a welcome which notifies users of their current global
        access level.
    """
    @defer.inlineCallbacks
    def st_receive_uid(self,**kwargs):
        user = kwargs.get('user')
      
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
            

        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        self.user_trigger_welcome(user,db_user)
        
    
    """
        Gives the user a welcome message and executes any autojoins that they may
        have.
    """
    def user_trigger_welcome(self,user,db_user):
        ajchans = db_user.get('autojoin')
        if not self.factory.is_bursting:
            if ajchans:
                for chan in ajchans.split(','):
                    self.protocol.st_send_command('SVSJOIN',[user.uid,chan],self.factory.cfg.server.sid)

    
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Welcome %s! Your current global access level is %s.' % (user.nick,db_user.get('level',0)))
            
    
          
     
    """
        Handles Enforcer CHANLEVEL command, using internal functions for error output
        and initial docstring for HELP output.
    """
    @defer.inlineCallbacks
    def ps_privmsg_chanlevel(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100> 
            Access:         FOUNDER ONLY
            Description:    Sets the minimum levels on a channel to be 
                            automatically granted access, voice, halfop, op,
                            or protected op respectively.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] (USERLEVEL) Usage: CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100>')
            
        def no_change(chan,type,level):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s already has %s access level of %s' % (chan,type,level))
            
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def level_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s %s access level set to: %s' % (kwargs.get('chan'),kwargs.get('type'),kwargs.get('level')))
            
        def conflicting_mode(*args):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[ERROR] %s level (%s) may not be below that of %s (%s)' % args)
            
        channel_name = ''
        new_level = ''
        
        # Attempt to split message into arguments, cast them
        # if required and check them for validity.
        try:
        
            channel_name,type,new_level = message.split(' ')
            new_level = int(new_level)
            type = type.upper()
            
            if type not in ('MIN','VOICE','HOP','OP','SOP'):
                raise ValueError('Invalid Value')
                
            if new_level < 1 or new_level > 100:
                raise ValueError('Invalid Value')
            
        except ValueError:
            usage()
            return 
        
        # Look up the channel and the user UID in question
        channel = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
            
        # If either of them don't exist, show usage
        if not channel or not user:
            usage()
            return
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return 
            
            
        # If there is no change to the level, show message
        if db_channel['min_level'] == new_level:
            no_change(channel.uid,type,new_level)
            return 
            
            
        # Otherwise set value based on TYPE field
        # !!! TODO: Clean this up somehow, it's ugly
        if type in ('MIN'):
            if new_level > db_channel['level_voice']:
                conflicting_mode('VOICE',db_channel['level_voice'],'MIN',new_level)
                return
            db_field = 'min_level'
            
            
        elif type in ('VOICE'):
            if new_level >= db_channel['level_halfop']:
                conflicting_mode('HALFOP',db_channel['level_halfop'],'VOICE',new_level)
                return
            # Leave this at < rather than <= so its possible to auto voice all users
            # on join.
            elif new_level < db_channel['min_level']:
                conflicting_mode('VOICE',db_channel['level_voice'],'MIN',db_channel['min_level'])
                return

            db_field = 'level_voice'
            
            
        elif type in ('HALFOP','HOP'):
            if new_level >= db_channel['level_op']:
                conflicting_mode('OP',db_channel['level_op'],'HALFOP',new_level)
                return
            elif new_level <= db_channel['level_voice']:
                conflicting_mode('HALFOP',db_channel['level_halfop'],'VOICE',db_channel['level_voice'])
                return
                
            db_field = 'level_halfop'
            
            
        elif type in ('OP'):
            if new_level >= db_channel['level_superop']:
                conflicting_mode('SOP',db_channel['level_superop'],'OP',new_level)
                return
            elif new_level <= db_channel['level_halfop']:
                conflicting_mode('OP',db_channel['level_op'],'HOP',db_channel['level_halfop'])
                return
                
            db_field = 'level_op'
        
        
        elif type in ('SOP','PROTECTED'):
            if new_level <= db_channel['level_op']:
                conflicting_mode('SOP',db_channel['level_superop'],'OP',db_channel['level_op'])
                return
                
            db_field = 'level_superop'
            
            
        # Update the db with the level from local data, then run an access pass
        # over the channel to change modes on all users if required
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET " + db_field + " = %s WHERE id = %s LIMIT 1", 
                [new_level,db_channel['id']]
            ).addCallbacks(level_updated,self.query_error_callback,None,{'chan': channel.uid,'type': type, 'level': new_level})
        
        self.access_level_pass(users=channel.users,channel=channel)
        
        return
        
    """
        Provides help command support for the Enforcer 
        pseudoclient.
    """
    def ps_privmsg_help(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          HELP [COMMAND]
            Access:         ALL USERS
            Description:    Returns list of available commands or returns help
                            documentation for a command if one is specified.
        """
        
        if pseudoclient_uid != self.factory.enforcer.uid:
            return False
       
        
        if message != '':
            m = tools.get_docstring(self.__class__,'ps_privmsg_',message)
            
            if m is True:
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'There is more than one command matching %s, please be more specific.' % message.upper())
            elif m is False or m is None:
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'No help for %s available.' % message.upper())
            
            elif m is not None:
                line = m.split('\n')
                for l in line:
                    self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,l)
            
            
        else:
            mlist = tools.find_names(self.__class__,r'(?i)^ps_privmsg_.+$')
            
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'The following commands are available by messaging (/msg) %s:' % self.factory.enforcer.nick)
            for method in mlist:
                cmd_name = method.split('_').pop().upper()
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,' ' + cmd_name)
        
        return True
        
        
    """
        Set the channel type of a channel
    """
    @defer.inlineCallbacks
    def ps_privmsg_chantype(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST
            Access:         FOUNDER ONLY
            Description:    Sets the type of channel for authentication purposes.
            
            USERLEVEL:      modes + access given to a user are based on their 
                            global user level and the CHANLEVEL settings of 
                            the named channel.
                        
            ACCESSLIST:     modes + access given to a user are based on the 
                            access list maintained by the founder of the channel.
                        
            PUBLIC_:        Specifying this before either of these two types 
                            of channel allows public access to the channel 
                            (any level user may join), and only modes given 
                            are defined by the channel type.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST')
        
        def no_change(chan,type):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s already has type %s' % (chan,type))
        
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def type_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s type changed to: %s' % (kwargs.get('chan'),kwargs.get('type')))
        
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
        channel_name = ''
        new_type = ''
        
        try:
        
            channel_name,new_type = message.split(' ')
            new_type = new_type.upper()
            
            if new_type not in ('PUBLIC_USERLEVEL','PUBLIC_ACCESSLIST','USERLEVEL','ACCESSLIST'):
                raise ValueError('Invalid Type')
            
        except ValueError:
            usage()
            return
        
        channel = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
            
        if not channel or not user:
            usage()
            return
        
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return 

        if db_channel['type'] == new_type:
            no_change(channel.uid,new_type)
            return

        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET type = %s WHERE id = %s LIMIT 1", 
                [new_type,db_channel['id']]
            ).addCallbacks(type_updated,self.query_error_callback,None,{'chan': channel.uid,'type': new_type})
        
        self.access_level_pass(users=channel.users,channel=channel)
        
        return
        
        
    @defer.inlineCallbacks    
    def ps_privmsg_register(self,source_uid,command,message,pseudoclient_uid):
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[OPERATOR ONLY] Syntax: REGISTER #channel')
        
        def no_channel():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist' % (message))
        
        def already_registered():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s is already registered' % (message))
         
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[OPERATOR ONLY] <---- READ THIS (Access Denied)')
            
        @defer.inlineCallbacks    
        def channel_added(*args,**kwargs):
            chan = kwargs.get('chan')
            db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
            founder = kwargs.get('founder')
            
            self.access_level_pass(users=chan.users,channel=chan)
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s successfully registered to: %s' % (chan.uid,founder.nick))
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Your channel is set to type %s as default. You can change this with the CHANTYPE command (try /msg %s HELP).' % (db_channel['type'],self.factory.enforcer.nick))
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'You have been automatically given founder modes on %s.' % (chan.uid))
            
       
                
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
        
        channel = message.lower()
        # First make sure the channel name is valid
        if not channel.startswith('#'):
            usage()
            return 
   
        chan = self.protocol.lookup_uid(message)
        user = self.protocol.lookup_uid(source_uid)
        # Make sure the channel exists
        if not chan:
            no_channel()
            return
        
        if not user:
            usage()
            return
            
        # Check to see if the user is an OP on that channel
        if not chan.user_has_mode(user,'o'):
            access_denied()
            return
        
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_channel and db_user:
            cfg = self.factory.cfg.sqlextension
            self.factory.db.runOperation \
            (
                "INSERT INTO " + cfg.table_prefix + "_channels (name,founder_id) VALUES (%s,%s)", 
                [chan.uid,db_user['id']]
            ).addCallbacks(channel_added,self.query_error_callback,None,{'chan': chan, 'db_user': db_user, 'founder': user})
            
        else:
        
            already_registered()
            return

