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
from twisted.internet import reactor,defer


"""
    Acts as a container for extension functions which
    hook into the command delegation process.
"""
class SQLEnforcer(ext.BaseExtension):
    
    def __init__(self,*args,**kwargs):
        super(self.__class__, self).__init__(*args,**kwargs)
    
        
    """
        Hooks into the st_send_burst method allowing the extension to insert 
        its own pseudo-client UID's into the burst. This allows us to fake 
        network clients for the purposes of services.
    """
    def st_send_burst(self):
        cfg_enforcer = self.factory.cfg.sqlextension.services.enforcer
        #cfg_oper_tool = self.factory.cfg.sqlextension.services.oper_tool

        
        self.enforcer = self.protocol.st_add_pseudoclient(cfg_enforcer.nick,cfg_enforcer.host,cfg_enforcer.ident,'+iow',cfg_enforcer.realname,self)
        #self.oper_tool = self.protocol.st_add_pseudoclient(cfg_oper_tool.nick,cfg_oper_tool.host,cfg_oper_tool.ident,'+iow',cfg_oper_tool.realname,self,'oper')
        
        
    """
        Called on a timeout after a ban, this
        function unbans a given banmask on a 
        channel using the enforcer UID set 
        during net burst.
    """
    def do_unban(self,*args,**kwargs):
        channel = kwargs.get('channel')
        banmask = kwargs.get('banmask')

        self.protocol.st_send_command('SVSMODE',[channel.uid,'-b',banmask],self.enforcer.uid)
        self.log.log(cll.level.DEBUG,'Unbanned %s on %s (Timeban Expiry)' % (banmask,channel.uid))
        
        
    """
        This function enforces modes for a specific user
        on a specific channel using either their global
        access level or their access level on that channel,
        depending on the channel type.
    """
    def enforce_modes(self,*args,**kwargs):
        cfg_enforcer = self.factory.cfg.sqlextension.services.enforcer
        
        user = kwargs.get('user')
        channel = kwargs.get('channel')
        public = kwargs.get('public',False)
        
        _d = None
        _r = None

        
        # If user update for this is pending, add a callback to the pending method
        # AND if there was also a channel update pending, then chain them.
        if user.uid in self.factory.pending_users:
            self.factory.pending_users.get(user.uid).addCallback(getattr(self,tools.called_by(0)),**kwargs)
            return

        if user.db_id == channel.db_founder_id:
            effective_level = 100

        elif channel.db_type in ('ACCESSLIST','PUBLIC_ACCESSLIST'): 
            
            effective_level = channel.access.get(user.db_id,0)
                  
        else:
             effective_level = user.db_id
        

        # First check if users' level is equal or more
        # than the minimum level for this channel, otherwise
        # remove them if the channel is not public
        if effective_level < channel.db_min_level and not public:
        
            banmask = '*!*@%s' % user.displayed_hostname
            
            self.protocol.st_send_command('SVSMODE',[channel.uid,'-o+b',user.uid,banmask],self.enforcer.uid)
            self.protocol.st_send_command('SVSPART',[user.uid,channel.uid],self.enforcer.uid)
            self.protocol.st_send_command('NOTICE',[user.uid],self.enforcer.uid,'Access to %s denied by user level (%s < %s). You have been banned for %ss' % (channel.uid,effective_level,channel.db_min_level,cfg_enforcer.ban_accessdenied_expiry))
            
            reactor.callLater(cfg_enforcer.ban_accessdenied_expiry, self.do_unban,channel=channel,banmask=banmask)
            
            self.log.log(cll.level.DEBUG,'Banned %s on %s (%ss Access denied timeban)' % (banmask,channel.uid,cfg_enforcer.ban_accessdenied_expiry))
            return

        give_user = ''
        take_user = ''
        
        modes_order = 'qaohv'
        give = ''
        take = ''
        
        if user.db_id == channel.db_founder_id:
            # Remove nothing, user is the channel founder
            # so give founder mode + all trimmings 
            give = modes_order
            
        elif effective_level >= channel.db_level_superop:
            # Remove nothing, superops are awesome.
            # Give them all roles up to superop
            give = modes_order[1:]
            take = modes_order[0]
            
        elif effective_level >= channel.db_level_op:
            # Remove superops only (no-one should ever have this)
            # because SOP is given by services only
            give = modes_order[2:]
            take = modes_order[:2]

            
        elif effective_level >= channel.db_level_halfop:
            # Remove ops
            give = modes_order[3:]
            take = modes_order[:3]

            
        elif effective_level >= channel.db_level_voice:
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
        self.protocol.st_send_command('SVSMODE',[channel.uid,give + take,give_user,take_user],self.enforcer.uid)
        
        
    def access_level_pass(self,*args,**kwargs):
        users = kwargs.get('users')
        channel = kwargs.get('channel')
       
        
        if not channel or not users:
            return 
    

        # Check if channel has a founder first 
        if not hasattr(channel,'db_founder_id'):
            # Channel is not registered, we don't care.
            return
        
        # Channel is registered, set modes / remove users based
        # on the type of channel.
        
        for uitem in users.values():
            user = uitem.get('instance')
            modes = uitem.get('modes')
            
            if channel.db_type in ('USERLEVEL','ACCESSLIST','PUBLIC_USERLEVEL','PUBLIC_ACCESSLIST'):
                if channel.db_type.startswith('PUBLIC_'):
                    self.enforce_modes(user=user,channel=channel,public=True)
                else:
                    self.enforce_modes(user=user,channel=channel)
                    
            else:
                # Channels without a channel type will get handled 
                # like a PUBLIC_USERLEVEL channel, although this 
                # should never happen.
                self.enforce_modes(user=user,channel=channel,public=True)	
                    
    
    def st_receive_fjoin(self,timestamp,channel,users,modes):

        channel_uid = self.protocol.lookup_uid(channel)
        
        if not channel_uid:
            self.log.log(cll.level.ERROR,'We received a hook FJOIN but the channel could not be looked up by UID :wtc:')
            return False
   
        if channel_uid.uid in self.factory.pending_channels:
            _d = self.factory.pending_channels.get(channel_uid.uid).addCallback(self.access_level_pass,users=channel_uid.users,channel=channel_uid)
            
        else:
            self.access_level_pass(users=channel_uid.users,channel=channel_uid)
        
        return True  

        
    def st_receive_uid(self,**kwargs):
        user = kwargs.get('user')
      
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
            

        if user.uid in self.factory.pending_users:
            _d = self.factory.pending_users.get(user.uid).addCallback(self.user_trigger_welcome,user=user)
            return
        
        self.user_trigger_welcome(user=user)
        
        
    def user_trigger_welcome(self,*args,**kwargs):
        user = kwargs.get('user')
        if user:
            # Do autojoins here
            if hasattr(user,'autojoin'):
                if user.autojoin:
                    for chan in user.autojoin.split(','):
                        self.protocol.st_send_command('SVSJOIN',[user.uid,chan],self.factory.cfg.server.sid)

            if not self.factory.is_bursting:
                self.protocol.st_send_command('NOTICE',[user.uid],self.enforcer.uid,'Welcome %s! Your current global access level is %s.' % (user.nick,user.db_level))
                
        return True
          
     
    def ps_privmsg_chanlevel(self,command,message,pseudoclient_uid,source_uid):
        """
    Usage:          CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100> 
    Access:         FOUNDER ONLY
    Description:    Sets the minimum levels on a channel to be automatically 
                    granted access, voice, halfop, op, or protected op respectively.
        """
        
        def usage():
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] (USERLEVEL) Usage: CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100>')
            
        def no_change(chan,type,level):
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s already has %s access level of %s' % (chan,type,level))
            
        def access_denied():
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def level_updated(*args,**kwargs):
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s %s access level set to: %s' % (kwargs.get('chan'),kwargs.get('type'),kwargs.get('level')))
            
        def conflicting_mode(*args):
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[ERROR] %s level (%s) may not be below that of %s (%s)' % args)
            
        channel_name = ''
        new_level = ''
        
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
            return False
        
        channel = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
            
        if not channel or not user:
            usage()
            return False
            
        if channel.db_min_level == new_level:
            no_change(channel.uid,type,new_level)
            return False
            
        if channel.db_founder_id != user.db_id:
            access_denied()
            return False
            
        if type in ('MIN'):
            if new_level > channel.db_level_voice:
                conflicting_mode('VOICE',channel.db_level_voice,'MIN',new_level)
                return
            channel.db_min_level = new_level
            db_field = 'min_level'
            
        elif type in ('VOICE'):
            if new_level >= channel.db_level_halfop:
                conflicting_mode('HALFOP',channel.db_level_halfop,'VOICE',new_level)
                return
            # Leave this at < rather than <= so its possible to auto voice all users
            # on join.
            elif new_level < channel.db_min_level:
                conflicting_mode('VOICE',channel.db_level_voice,'MIN',channel.db_min_level)
                return
                
            channel.db_level_voice = new_level
            db_field = 'level_voice'
            
        elif type in ('HALFOP','HOP'):
            if new_level >= channel.db_level_op:
                conflicting_mode('OP',channel.db_level_op,'HALFOP',new_level)
                return
            elif new_level <= channel.db_level_voice:
                conflicting_mode('HALFOP',channel.db_level_halfop,'VOICE',channel.db_level_voice)
                return
                
            channel.db_level_halfop = new_level
            db_field = 'level_halfop'
            
        elif type in ('OP'):
            if new_level >= channel.db_level_superop:
                conflicting_mode('SOP',channel.db_level_sop,'OP',new_level)
                return
            elif new_level <= channel.db_level_halfop:
                conflicting_mode('OP',channel.db_level_op,'HOP',chan.db_level_halfop)
                return
                
            channel.db_level_op = new_level
            db_field = 'level_op'
        
        elif type in ('SOP','PROTECTED'):
            if new_level <= channel.db_level_op:
                conflicting_mode('SOP',channel.db_level_superop,'OP',chan.db_level_op)
                return
                
            channel.db_level_superop = new_level
            db_field = 'level_superop'
            
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET " + db_field + " = %s WHERE id = %s LIMIT 1", 
                [new_level,channel.db_id]
            ).addCallbacks(level_updated,self.query_error_callback,None,{'chan': channel.uid,'type': type, 'level': new_level})
        
        self.access_level_pass(users=channel.users,channel=channel)
        
        return False
        
             
    def ps_privmsg_help(self,command,message,pseudoclient_uid,source_uid):
        """
    Usage:          HELP [COMMAND]
    Access:         ALL USERS
    Description:    Returns list of available commands or returns help
                    documentation for a command if one is specified.
        """
        if pseudoclient_uid != self.enforcer.uid:
            return False
       
        
        if message != '':
            m = tools.get_docstring(self.__class__,'ps_privmsg_',message)
            
            if m is True:
                self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'There is more than one command matching %s, please be more specific.' % message.upper())
            elif m is False or m is None:
                self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'No help for %s available.' % message.upper())
            
            elif m is not None:
                line = m.split('\n')
                for l in line:
                    self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,l)
            
            
        else:
            mlist = tools.find_names(self.__class__,r'(?i)^ps_privmsg_.+$')
            
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'The following commands are available by messaging (/msg) %s:' % self.enforcer.nick)
            for method in mlist:
                cmd_name = method.split('_').pop().upper()
                self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,' ' + cmd_name)
        
        return True
        
        
    def ps_privmsg_chantype(self,command,message,pseudoclient_uid,source_uid):
        """
    Usage:          CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST
    Access:         FOUNDER ONLY
    Description:    Sets the type of channel for authentication purposes.
 
 
        USERLEVEL:  modes + access given to a user are based on their 
                    global user level and the CHANLEVEL settings of 
                    the named channel.
                    
        ACCESSLIST: modes + access given to a user are based on the 
                    access list maintained by the founder of the channel.
                    
        PUBLIC_:    Specifying this before either of these two types 
                    of channel allows public access to the channel 
                    (any level user may join), and only modes given 
                    are defined by the channel type.
        """
        
        def usage():
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST')
        
        def no_change(chan,type):
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s already has type %s' % (chan,type))
        
        def access_denied():
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def type_updated(*args,**kwargs):
            self.protocol.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s type changed to: %s' % (kwargs.get('chan'),kwargs.get('type')))
        
        if pseudoclient_uid != self.enforcer.uid:
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
            return False
        
        channel = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
            
        if not channel or not user:
            usage()
            return False
            
        if channel.db_type == new_type:
            no_change(channel.uid,new_type)
            return False
            
        if channel.db_founder_id != user.db_id:
            access_denied()
            return False
        

        channel.db_type = new_type.upper()
        
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET type = %s WHERE id = %s LIMIT 1", 
                [channel.db_type,channel.db_id]
            ).addCallbacks(type_updated,self.query_error_callback,None,{'chan': channel.uid,'type': channel.db_type})
        
        self.access_level_pass(users=channel.users,channel=channel)
        
        return False
        
        
    def ps_privmsg_register(self,source_uid,command,message,pseudoclient_uid):
        if pseudoclient_uid != self.enforcer.uid:
            return
        self.protocol.st_send_command('PRIVMSG',[source_uid.uid],pseudoclient_uid,'Registering %s' % str(message))
        return True
            