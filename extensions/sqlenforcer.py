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
import common.uid_types as uid
from pprint import pprint, pformat

from twisted.enterprise import adbapi 
from twisted.internet import reactor
from twisted.internet import defer



"""
    Acts as a container for extension functions which
    hook into the command delegation process.
"""
class SQLEnforcer(ext.BaseExtension):
    required_extensions = ['SQLExtension']
    
    bad_behaviour_reg = {}
    
    def __init__(self,*args,**kwargs):
        super(self.__class__, self).__init__(*args,**kwargs)
    
        self.sqe = self.factory.loaded_extensions.get('SQLExtension')
        

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
        
    def kill_user(self,nick):
        self.protocol.st_send_command('KILL',[nick],self.factory.enforcer.uid,'Your nick has been updated or removed.')
        return True
        
    def bad_behaviour(self,user,value,timeout=600):
        cfg_bad_behaviour = self.factory.cfg.sqlextension.services.enforcer.bad_behaviour
        
        def send_warning(value,threshold):
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,cfg_bad_behaviour.warning % (value,threshold))
            
        def send_removal(value,cur_value,threshold):
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,cfg_bad_behaviour.removed % (value,cur_value,threshold))
              
        def remove_bad_behaviour(user,value):
            if user.uid in self.bad_behaviour_reg:
                cur_val = self.bad_behaviour_reg.get(user.uid)
                
                if cur_val > value:
                    self.bad_behaviour_reg[user.uid] = cur_val - value
                    send_removal(value,self.bad_behaviour_reg[user.uid],cfg_bad_behaviour.threshold)
                else:
                    del self.bad_behaviour_reg[user.uid]
                    send_removal(value,0,cfg_bad_behaviour.threshold)
                    

        if not cfg_bad_behaviour.enabled:
            return False
            
        if user.uid not in self.bad_behaviour_reg:
            self.bad_behaviour_reg[user.uid] = value
            send_warning(self.bad_behaviour_reg[user.uid],cfg_bad_behaviour.threshold)
            reactor.callLater(timeout, remove_bad_behaviour,user,value)
            return False
        else:
            cur_val = self.bad_behaviour_reg.get(user.uid)
            
            self.bad_behaviour_reg[user.uid] = cur_val + value
            
            if self.bad_behaviour_reg[user.uid] >= cfg_bad_behaviour.threshold:
                # kill user
                self.protocol.st_send_command('KILL',[user.nick],self.factory.enforcer.uid,cfg_bad_behaviour.reason)
                return True
            else:
                
                send_warning(self.bad_behaviour_reg[user.uid],cfg_bad_behaviour.threshold)
                reactor.callLater(timeout, remove_bad_behaviour,user,value)
                return False
        
        
    def st_receive_ftopic(self,*args,**kwargs):
        return self.topic_enforce(*args,**kwargs)
        
    def st_receive_topic(self,*args,**kwargs):
        return self.topic_enforce(*args,**kwargs)
     
     
    @defer.inlineCallbacks
    def topic_enforce(self,user,channel,topic):
         
         
        def topic_updated(*args,**kwargs):
            channel = kwargs.get('channel')
            user = kwargs.get('user')
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'%s topic updated.' % channel)
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
        
        
        if user:
            db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        else:
            db_user = None

        
        if db_channel:
            db_topic = db_channel.get('topic')
            
            if db_topic and db_topic != topic and db_channel['topic_protection']:
                
                if not db_user:
                    # User not found, this probably means this came from a network burst FTOPIC
                    # At this point we enforce the topic at all times, since we don't know who
                    # set it last.
                    self.protocol.st_send_command('TOPIC',[channel.uid],self.factory.enforcer.uid,db_topic)
                    
                elif db_user['id'] != db_channel['founder_id']:
                    # Channel topic is incorrect and must be enforced, this user is not channel founder
                    self.protocol.st_send_command('TOPIC',[channel.uid],self.factory.enforcer.uid,db_topic)
                    cfg_bad_behaviour = self.factory.cfg.sqlextension.services.enforcer.bad_behaviour
                    self.bad_behaviour(user,cfg_bad_behaviour.value_topic_enforce,cfg_bad_behaviour.timeout_topic_enforce)
                else:
                    # Channel topic changed by founder, record it
                    cfg = self.factory.cfg.sqlextension
                    self.factory.db.runOperation \
                        (
                            "UPDATE " + cfg.table_prefix + "_channels SET topic = %s WHERE id = %s LIMIT 1", 
                            [topic,db_channel['id']]
                        ).addCallbacks(topic_updated,self.query_error_callback,None,{'channel': channel.uid,'user': user})
                    

                    
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
    
    def enforce_user_modes(self,user,db_user,channel,db_channel,db_accesslist):
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
            if db_user['id'] in db_accesslist:
                effective_level = db_accesslist[db_user['id']].get('access_level',0)
            else:
                effective_level = 0
        else:
             effective_level = db_user['level']
        
       
        # First check if users' level is equal or more
        # than the minimum level for this channel, otherwise
        # remove them if the channel is not public
       
        if effective_level < db_channel['min_level'] and not public:
            cfg_bad_behaviour = self.factory.cfg.sqlextension.services.enforcer.bad_behaviour
            
            banmask = cfg_bad_behaviour.banmask % user.__dict__

            if not self.bad_behaviour(user,cfg_bad_behaviour.value_accessdenied_enforce,cfg_bad_behaviour.timeout_accessdenied_enforce):
                    
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
            give_user = ' '.join([user.uid] * len(give))
            give = '+' + give

        if take:
            take_user = ' '.join([user.uid] * len(take))
            take = '-' + take
            
        
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
        

        if isinstance(users,dict):
            # Get all users at once so not to spam queries
            user_nicks = [user['instance'].nick for user in users.values()]
        
            db_users = yield self.factory.db.runInteraction(self.sqe.get_users_complete,user_nicks)
            
            for uitem in users.values():
                user = uitem.get('instance')
                modes = uitem.get('modes')
                
                db_user = db_users.get(user.nick,None)
                
                if not db_user:
                    self.kill_user(user.nick)
                    
                self.enforce_user_modes(user,db_user,channel,db_channel,db_accesslist)
                
        else:   
            user = users
            db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
            self.enforce_user_modes(user,db_user,channel,db_channel,db_accesslist)
            

    """
        This command is hooked when a mode is set.
    """
    @defer.inlineCallbacks
    def st_receive_fmode(self,source_uid,channel,timestamp,modes):
        def mode_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],self.factory.enforcer.uid,'Channel %s mode %s recorded value: %s' % (kwargs.get('chan'),kwargs.get('mode'),kwargs.get('value')))
        
        def mode_deleted(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],self.factory.enforcer.uid,'Channel %s mode %s removed value: %s'% (kwargs.get('chan'),kwargs.get('mode'),kwargs.get('value')))
            
        user = self.protocol.lookup_uid(source_uid)
        
        if not channel:
            self.log.log(cll.level.ERROR,'We received a hook FMODE but the channel could not be looked up by UID :wtc:')
            return
        
        if not isinstance(user,uid.User):
            self.log.log(cll.level.ERROR,'We received a hook FMODE but the user could not be looked up by UID :wtc:')
            return
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
            
        if not db_channel:
            # Channel is not registered, ignore it
            return
                
        db_channel_modes = yield self.factory.db.runInteraction(self.sqe.get_channel_modes,channel.uid)    
        db_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,channel.uid)
        
        # If channel wants to enforce user modes, loop over all applied modes
        # Looking for prefix modes, then run an access pass over each user
        # whos' prefix mode has changed, using passed to record which users
        # we have run an access level pass on (so we dont run multiples for 
        # multiple mode changes.

        ump = db_channel.get('user_mode_protection',0) 
        cmp = db_channel.get('channel_mode_protection',0) 
        
        passed = []
        
        am = tools.applied_modes(modes)
        for mode, value in am.items():
            give,param = value
            _type = self.protocol.lookup_mode_type(mode,channel)
            
            
            # Mode change was on a prefix (qaohv) mode and has not been ran yet
            if tools.contains_any('X',_type) and param not in passed and ump:
                passed.append(param)
                db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,param.nick)
                
                if not db_user:
                    self.kill_user(param.nick)
                    
                self.enforce_user_modes(param,db_user,channel,db_channel,db_accesslist)
                
            elif cmp and tools.contains_any('BCD',_type):
                # Mode was a channel mode, and channel mode protection is on.
                # We only want to enforce non-type-A ("Mode that adds or removes
                # a nick or address to a list") modes because bans should be 
                # handled by channel ops or access lists.
                
                if not isinstance(user,uid.User):
                    self.enforce_channel_mode(channel=channel,db_modes=db_channel_modes,mode=mode,value=value) 
                else:
                    db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
                    
                    if not db_user:
                        self.kill_user(user.nick)
                        self.enforce_channel_mode(channel=channel,db_modes=db_channel_modes,mode=mode,value=value) 
                        return
                        
                    # First check if the user who set the mode was founder, if so, save it
                    # Else enforce mode change
                    if db_user['id'] == db_channel['founder_id']:
                        # User is founder, modify / delete mode
                        
                        value = param
                        if not value:
                            value = ''
                            
                        cfg = self.factory.cfg.sqlextension
                        
                        if give: 
                            # User is adding or editing an existing mode, insert or update
                            self.factory.db.runOperation \
                                (
                                    "INSERT INTO  " + cfg.table_prefix + "_channel_modes (channel_id,mode,value) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE value = VALUES(value)", 
                                    [db_channel['id'],mode,value]
                                ).addCallbacks(mode_updated,self.query_error_callback,None,{'chan': channel.uid, 'mode': mode, 'value': param})
            
                        else:
                            # User is unsetting a mode, delete it
                            self.factory.db.runOperation \
                                (
                                    "DELETE FROM " + cfg.table_prefix + "_channel_modes WHERE channel_id = %s AND mode = %s LIMIT 1", 
                                    [db_channel['id'],mode]
                                ).addCallbacks(mode_deleted,self.query_error_callback,None,{'chan': channel.uid, 'mode': mode, 'value': param})
                    else:
                        self.enforce_channel_mode(channel=channel,db_modes=db_channel_modes,mode=mode,value=value) 
                    
     
        
        
    def enforce_channel_mode(self,channel,db_modes,mode,value):
        
        def enforce_mode(mode,value,give):
            if not value: 
                value = ''
                
            if give:
                ms = '+'
            else:
                ms = '-'
            self.protocol.st_send_command('SVSMODE',[channel.uid,ms + mode,value],self.factory.enforcer.uid)
    
    
        give,param = value
            
        if mode in db_modes:
            # Mode has an enforcement value listed in DB
            
            if not give:
                # Enforced mode has been removed, re-add it
                enforce_mode(mode,db_modes.get(mode,''),True)
            
            elif param != db_modes.get(mode):
                # If mode is still enforced but with incorrect value, re-enforce it
                enforce_mode(mode,db_modes.get(mode,''),True)
            else:
                # Mode has just been re-set with correct value, ignore
                pass
        
        else:
            # Mode is not an enforced mode, so remove it
            enforce_mode(mode,param,False)
               
                     
                
    """
        This command is hooked when someone joins a channel.
    """
    @defer.inlineCallbacks
    def st_receive_fjoin(self,timestamp,channel,users,modes):

        channel_uid = self.protocol.lookup_uid(channel)
        
        if not channel_uid:
            self.log.log(cll.level.ERROR,'We received a hook FJOIN but the channel could not be looked up by UID :wtc:')
            return
        
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel_uid.uid)
            
        if not db_channel:
            # Channel is not registered
            # If this is a single user join, check to see if they have 
            # permissions to make the channel and if not, punish
            if len(channel_uid.users) == 1:
                for user in users:
                    user_uid = self.protocol.lookup_uid(user)
                    db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user_uid.nick)
                    if not db_user:
                        self.kill_user(user_uid.nick)
                        return
                    self.enforce_create_channel_access(user_uid,db_user,channel_uid)
            return
                
        db_channel_modes = yield self.factory.db.runInteraction(self.sqe.get_channel_modes,channel_uid.uid)    

  
        
        # Every join, attempt to apply any removed modes from a channel.
        # This means that when a channel is created by a join, its' 
        # enforced modes are set during that join.
        am = tools.applied_modes(modes)
        for mode, value in db_channel_modes.items():
            if mode in am:
                continue
                
            _type = self.protocol.lookup_mode_type(mode,channel_uid)
            
            if tools.contains_any('BCD',_type):
                self.protocol.st_send_command('SVSMODE',[channel_uid.uid,'+' + mode,value],self.factory.enforcer.uid)
                
                
            
        
        if self.factory.is_bursting:
            self.access_level_pass(users=channel_uid.users,channel=channel_uid)
        else:
           
            db_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,channel_uid.uid)
            
            for user in users:
                user_uid = self.protocol.lookup_uid(user)
                if not user_uid:
                    break
                db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user_uid.nick)
                if not db_user:
                    self.kill_user(user_uid.nick)
                    return
                self.enforce_user_modes(user_uid,db_user,channel_uid,db_channel,db_accesslist)
        


    def enforce_create_channel_access(self,user,db_user,channel):
        cfg_enforcer = self.factory.cfg.sqlextension.services.enforcer
        
        effective_level = db_user['level']
        
        if effective_level < cfg_enforcer.level_chancreate_min and cfg_enforcer.enforce_chancreate_limit:
            
                
                cfg_bad_behaviour = self.factory.cfg.sqlextension.services.enforcer.bad_behaviour
                if not self.bad_behaviour(user,cfg_bad_behaviour.value_chancreatedenied_enforce,cfg_bad_behaviour.timeout_chancreatedenied_enforce):
                        
                    self.protocol.st_send_command('SVSPART',[user.uid,channel.uid],self.factory.enforcer.uid)
                    self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Channel %s creation denied by user level (%s < %s).' % (channel.uid,effective_level,cfg_enforcer.level_chancreate_min))
                    
                    self.log.log(cll.level.DEBUG,'Parted %s on %s (Channel Create denied)' % (user.nick,channel.uid))
                    
        return
     
    """
        Called when we receive a NICK command. Since the entire
        SQL system relies on nicknames being disabled, this will
        probably only be called by an oper forcing nick changes.
        We want to auto-kill anyone whos' nick gets changed so
        problems are not caused by non-existent nicknames in the DB.
    """
    def st_receive_nick(self,uid,args):
        self.protocol.st_send_command('KILL',[uid],self.factory.enforcer.uid,'Nickname changes are not allowed.')
        
        
    """
        This is called when we receive a new UID from the peer server,
        either during the connect sequence or when a new client is 
        introduced. We trigger a welcome which notifies users of 
        their current global access level.
    """
    @defer.inlineCallbacks
    def st_receive_uid(self,**kwargs):
        user = kwargs.get('user')
      
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
            

        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
            
        self.user_trigger_welcome(user,db_user)
        
    
    def invite_svsjoin(self,user,channel):
        self.protocol.st_send_command('INVITE',[user.uid,channel],self.factory.enforcer.uid)
        self.protocol.st_send_command('SVSJOIN',[user.uid,channel],self.factory.cfg.server.sid)
        
        
    """
        Gives the user a welcome message and executes any autojoins that they may
        have.
    """
    @defer.inlineCallbacks
    def user_trigger_welcome(self,user,db_user):
        ajchans = db_user.get('autojoin')
        if not self.factory.is_bursting:
            if ajchans:
                for chan in ajchans.split(','):
                    # Get permissions for channel, if user has access force them to join
                    db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan)
                    
                    # If autojoin contains an invalid channel, skip it
                    if not db_channel:
                        continue
                        
                    if db_user['id'] == db_channel['founder_id']:
                        self.invite_svsjoin(user,chan)
                    
                        
                    
                    # If channel runs an access list, check for permissions there
                    elif db_channel['type'] in ('ACCESSLIST'):
                        db_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,chan)
                        
                        if db_user['id'] in db_accesslist: 
                            self.invite_svsjoin(user,chan)
                        else:
                            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Did not AJOIN you to %s because you do not have sufficient access privileges.' % (user.nick,chan))
                            self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
                            
                    # Otherwise, check for permissions using global level
                    elif db_channel['type'] in ('USERLEVEL'):
                        if db_user.get('level',0) >= db_channel['min_level']: 
                            self.invite_svsjoin(user,chan)
                        else:
                            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Did not AJOIN you to %s because you do not have sufficient access privileges.' % (user.nick,chan))
                            self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
                            
                    elif db_channel['type'] in ('PUBLIC_ACCESSLIST','PUBLIC_USERLEVEL'):
                        self.invite_svsjoin(user,chan)
                    
                    else:
                        self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Did not AJOIN you to %s because you do not have sufficient access privileges.' % (user.nick,chan))
                        self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
                        
            self.protocol.st_send_command('NOTICE',[user.uid],self.factory.enforcer.uid,'Welcome %s! Your current global access level is %s.' % (user.nick,db_user.get('level',0)))
            
    
         
    """
        Handles Enforcer INVITE command, using internal functions for error output
        and initial docstring for HELP output.
    """
    @defer.inlineCallbacks
    def ps_privmsg_invite(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          INVITE #channel
            Access:         ALL USERS
            Description:    Requests an invite from services to a specific
                            channel. If the channel is +i and the user has
                            the relevant access levels, they will be given
                            an invite to the channel and then force-joined.
        """
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[ALL USERS] Usage: INVITE #channel')
       
       
        def not_registered(channel):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s is not registered - invites cannot be given.' % (channel))
              
        def no_channel(channel):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist (it may be empty, in this case just join as usual).' % (channel))
        
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Access Denied: You must have rights in the channel you\'re requesting an invite for.')
            
            
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
                

        # First make sure the channel name is valid
        if not message.startswith('#'):
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
            
        
       
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
            
        if not db_channel:
            not_registered()
            return
            
       
        
        if db_user['id'] == db_channel['founder_id']:
            self.invite_svsjoin(user,chan.uid)
            
        elif db_channel['type'] in ('ACCESSLIST'):
            db_channel_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,chan.uid)
            
            if db_user['id'] in db_accesslist: 
                self.invite_svsjoin(user,chan.uid)
            else:
                access_denied()
                self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
                
        elif db_channel['type'] in ('USERLEVEL'):
        
            if db_user.get('level',0) >= db_channel['min_level']: 
                self.invite_svsjoin(user,chan.uid)
            else:
                access_denied()
                self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
                
        elif db_channel['type'] in ('PUBLIC_ACCESSLIST','PUBLIC_USERLEVEL'):
            self.invite_svsjoin(user,chan.uid)
            
        else:
            access_denied()
            self.log.log(cll.level.INFO,'User %s has no access to %s' % (user.nick,chan))
            
            
    """
        Handles Enforcer AJOIN command, using internal functions for error output
        and initial docstring for HELP output.
    """
    @defer.inlineCallbacks
    def ps_privmsg_ajoin(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          AJOIN ADD|DEL|LIST [#channel]
            Access:         ALL USERS
            Description:    Adds a channel to your automatic join list.
                            On connect, you will be auto-joined to all
                            channels on the list that you have access 
                            to.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[ALL USERS] Usage: AJOIN ADD|DEL|LIST [#channel]')
        
        def duplicate_ajoin(channel):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s is already in your AJOIN list.' % (channel))
        
        def no_ajoin(channel):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s is not in your AJOIN list.' % (channel))
         
        def ajoin_added(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'%s added to your AJOIN list.' % (kwargs.get('chan')))
        
        def ajoin_deleted(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'%s deleted from your AJOIN list.' % (kwargs.get('chan')))
            
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
                
        channel_name = ''
        
        try:
        
            v = message.split(' ')
           
            if len(v) == 1:
                function, = v
            else:
                function, channel_name = v
                
            function = function.upper()
            
            
            if function not in ('ADD','DEL','LIST'):
                raise ValueError('Invalid Function')
                
            
        except ValueError:
                usage()
                return   

        # Look up the channel and the user UID in question
        channel = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
            
        # If either of them don't exist, show usage
        if (not channel and function in ('ADD','DEL')) or not user:
            usage()
            return    

        if function in ('ADD','DEL'):
            db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,channel.uid)
        else:
            db_channel = None
            
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel and function in ('ADD','DEL'):
            usage()
            return

        ajchans = db_user.get('autojoin')
        
        if not ajchans:
            ajchans = []
        else:
            ajchans = ajchans.split(',')
        
        
            
        cfg = self.factory.cfg.sqlextension
        
        if function in ('ADD'):
            if channel_name in ajchans:
                duplicate_ajoin(channel_name)
                return
            
            self.factory.db.runOperation \
                (
                    "INSERT INTO " + cfg.table_prefix + "_user_autojoin (user_id,channel_id) VALUES (%s,%s)", 
                    [db_user['id'],db_channel['id']]
                ).addCallbacks(ajoin_added,self.query_error_callback,None,{'chan': channel.uid})
             
        elif function in ('DEL'):

            if channel_name not in ajchans:
                no_ajoin(channel_name)
                return
            
            self.factory.db.runOperation \
                (
                    "DELETE FROM " + cfg.table_prefix + "_user_autojoin WHERE user_id = %s AND channel_id = %s LIMIT 1", 
                    [db_user['id'],db_channel['id']]
                ).addCallbacks(ajoin_deleted,self.query_error_callback,None,{'chan': channel.uid})
             
        elif function in ('LIST'):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channels on your AJOIN List:')
            for chan in ajchans:
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'  %s' % (chan))    
                

       
    """
        Handles Enforcer CHANLEVEL command, using internal functions for error output
        and initial docstring for HELP output.
    """
    @defer.inlineCallbacks
    def ps_privmsg_chanlevel(self,command,message,pseudoclient_uid,source_uid):
        """
            Usage:          CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP|SET <1-100> 
            Access:         FOUNDER ONLY
            Description:    Sets the minimum levels on a channel to be 
                            automatically granted access, voice, halfop, op,
                            or protected op respectively. Any user with a
                            user level above the 'SET' minimum will be allowed
                            to manage the channel access list. SET defaults to
                            100 on channel creations so only SOP users and 
                            founders may manage the channel access list or 
                            other settings.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] (USERLEVEL) Usage: CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100>')
                
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

            channel_name,type,new_level = message.split(' ',3)
   
            new_level = int(new_level)
            type = type.upper()
            
            if type not in ('MIN','VOICE','HOP','OP','SOP','SET'):
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
        
        if not db_user:
            self.kill_user(user.nick)
            return
            
        if not db_channel:
            usage()
            return
            
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return 
          
        # Otherwise set value based on TYPE field
        # !!! TODO: Clean this up somehow, it's ugly
        
        if type in ('SET'):
            db_field = 'level_settings'
            
        elif type in ('MIN'):
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
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'  ' + cmd_name)
        
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
        
        def no_change(chan,typename):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s already has type %s' % (chan,typename))
        
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def type_updated(*args,**kwargs):
            chan = kwargs.get('chan')
            self.access_level_pass(users=chan.users,channel=chan)
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s type changed to: %s' % (chan.uid,kwargs.get('type')))
        
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
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel:
            usage()
            return      
            
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
            ).addCallbacks(type_updated,self.query_error_callback,None,{'chan': channel,'type': new_type})
        

        return

    @defer.inlineCallbacks    
    def ps_privmsg_usermodes(self,source_uid,command,message,pseudoclient_uid):
        """
            Usage:          USERMODES #channel ENFORCE <1|0>
            Access:         FOUNDER ONLY
            Description:    Allows you to set user mode enforcement on a channel
                            enabled or disabled.
                            
            ENFORCE:        With a value of 1 or 0, this turns mode enforcing
                            on and off. If enforce is on, only modes which the 
                            user has access to will be allowed to be given.
        """
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: USERMODES #channel ENFORCE <1|0>')
        
        def no_change(chan,function,value):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value USERMODES %s already has value %s' % (chan,function,value))
        
        def no_channel():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist' % (message))
             
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
         
        def modes_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value USERMODES %s changed to %s' % (kwargs.get('chan'),kwargs.get('function'),kwargs.get('value')))
            
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
            
             
        try:
           
            channel_name,function,value = message.split(' ',2)
            function = function.upper()
            
            if function not in ('ENFORCE'):
                raise ValueError('Invalid Type')
            else:

                value = int(value)
                if value > 1 or value < 0:
                    usage()
                    return
                    
      
        except ValueError:
            usage()
            return         
          
        
        channel = channel_name.lower()
        # First make sure the channel name is valid
        if not channel.startswith('#'):
            usage()
            return 

        chan = self.protocol.lookup_uid(channel)
        user = self.protocol.lookup_uid(source_uid)
        # Make sure the channel exists
        if not chan:
            no_channel()
            return
        
        if not user:
            usage()
            return 
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel:
            usage()
            return   
            
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return   
            
        if db_channel['user_mode_protection'] == value:
                no_change(chan.uid,function,value)
                return        
        
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET user_mode_protection = %s WHERE id = %s LIMIT 1", 
                [value,db_channel['id']]
            ).addCallbacks(modes_updated,self.query_error_callback,None,{'chan': chan.uid,'function': function,'value': value})

        
        return


    
    @defer.inlineCallbacks    
    def ps_privmsg_chanmodes(self,source_uid,command,message,pseudoclient_uid):
        """
            Usage:          CHANMODES #channel ENFORCE <1|0>
            Access:         FOUNDER ONLY
            Description:    Allows you to set channel mode enforcement enabled
                            or disabled.
                            
            ENFORCE:        With a value of 1 or 0, this turns mode enforcing
                            on and off. If enforce is on, only the founder is
                            able to modify channel modes.
        """
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: CHANMODES #channel ENFORCE <1|0>')
        
        def no_change(chan,function,value):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value CHANMODES %s already has value %s' % (chan,function,value))
        
        def no_channel():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist' % (message))
             
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
        
        def modes_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value CHANMODES %s changed to %s' % (kwargs.get('chan'),kwargs.get('function'),kwargs.get('value')))
            
        if pseudoclient_uid != self.factory.enforcer.uid:
                return
            
             
        try:
           
            channel_name,function,value = message.split(' ',2)
            function = function.upper()
            
            if function not in ('ENFORCE'):
                raise ValueError('Invalid Type')
            else:

                value = int(value)
                if value > 1 or value < 0:
                    usage()
                    return
                    
      
        except ValueError:
            usage()
            return         
          
        
        channel = channel_name.lower()
        # First make sure the channel name is valid
        if not channel.startswith('#'):
            usage()
            return 

        chan = self.protocol.lookup_uid(channel)
        user = self.protocol.lookup_uid(source_uid)
        # Make sure the channel exists
        if not chan:
            no_channel()
            return
        
        if not user:
            usage()
            return 
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel:
            usage()
            return       
            
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return   
            
        if db_channel['channel_mode_protection'] == value:
                no_change(chan.uid,function,value)
                return        
        
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET channel_mode_protection = %s WHERE id = %s LIMIT 1", 
                [value,db_channel['id']]
            ).addCallbacks(modes_updated,self.query_error_callback,None,{'chan': chan.uid,'function': function,'value': value})

        
        return
            
            
    @defer.inlineCallbacks    
    def ps_privmsg_chantopic(self,source_uid,command,message,pseudoclient_uid):
        """
            Usage:          CHANTOPIC #channel ENFORCE <1|0> | TOPIC <text>
            Access:         FOUNDER ONLY
            Description:    Allows you to change settings related to a channels'
                            topic on channels you own.
                            
            ENFORCE:        With a value of 1 or 0, this turns topic enforcing
                            on and off. If enforce is on, only the founder is
                            able to modify the topic and if the bad_behaviour
                            functionality is enabled, anyone changing the topic
                            will be warned and possibly killed.
            
            TOPIC:          Sets the text of the topic to be enforced. This can
                            also be set implicitly if the channel founder changes
                            the channel topic using /TOPIC while enforcement
                            is in effect.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: CHANTOPIC #channel ENFORCE <1|0> | TOPIC <text>')
        
        def no_change(chan,function,value):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value CHANTOPIC %s already has value %s' % (chan,function,value))
        
        def no_channel():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist' % (message))
         
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
          
        def topic_updated(*args,**kwargs):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s value CHANTOPIC %s changed to %s' % (kwargs.get('chan'),kwargs.get('function'),kwargs.get('value')))
            
                  
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
        
        try:
           
            channel_name,function,value = message.split(' ',2)
            function = function.upper()

            if function not in ('TOPIC','ENFORCE'):
                raise ValueError('Invalid Type')
            else:
                if function == 'ENFORCE':
                    value = int(value)
                    if value > 1 or value < 0:
                        usage()
                        return
                        
                    db_field = 'topic_protection'
                    
                elif function == 'TOPIC':
                    # TOPIC should already be a string
                    db_field = 'topic'
                    
                    
        except ValueError:
            usage()
            return
            
        channel = channel_name.lower()
        # First make sure the channel name is valid
        if not channel.startswith('#'):
            usage()
            return 
   
        chan = self.protocol.lookup_uid(channel)
        user = self.protocol.lookup_uid(source_uid)
        # Make sure the channel exists
        if not chan:
            no_channel()
            return
        
        if not user:
            usage()
            return 
            
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel:
            usage()
            return     
            
        # If user is not the channel founder, show message
        if db_channel['founder_id'] != db_user['id']:
            access_denied()
            return   
          
        if function in ('TOPIC'):
            self.protocol.st_send_command('TOPIC',[chan.uid],self.factory.enforcer.uid,value)
            
        elif function in ('ENFORCE') and db_channel['topic_protection'] == value:
            no_change(chan.uid,function,value)
            return

        
                   
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_channels SET " + db_field + " = %s WHERE id = %s LIMIT 1", 
                [value,db_channel['id']]
            ).addCallbacks(topic_updated,self.query_error_callback,None,{'chan': chan.uid,'function': function,'value': value})

        
        return
            
    
    @defer.inlineCallbacks    
    def ps_privmsg_chanacc(self,source_uid,command,message,pseudoclient_uid):
        """
            Usage:          CHANACC #channel ADD | DEL | LIST <nick | search_string> [<1-100>]
            Access:         BASED ON CHANNEL 'SETTINGS' LEVEL
            Description:    Allows you to list and modify the access list for 
                            a channel. You can explicitly set access levels for 
                            each user when the channel is set to ACCESSLIST or 
                            PUBLIC_ACCESSLIST. When the channel is set to 
                            USERLEVEL or PUBLIC_USERLEVEL, this access list will
                            not be used.
                            
            Note:           A nickname and access value, corresponding to the 
                            levels set using CHANLEVEL must be given for a 
                            CHANACC ADD, a search string must be given for a
                            CHANACC LIST (may be * for all), and a nickname 
                            must be given for CHANACC DEL.
        """
        
        def usage():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[TRUSTED ONLY] Syntax: CHANACC #channel ADD | DEL | LIST <nick | search_string> [<1-100>]')
        
        def no_channel(channel):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Channel %s does not exist' % (channel))
        
        def no_user(user):
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'User %s does not exist' % (user))
         
        def access_denied():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'[TRUSTED ONLY] <---- READ THIS (Access Denied)')
         
        def too_high():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'You may not modify users at or above YOUR access level!')
           
        def no_founder():
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'You may not add the channel founder to the access list - s/he already has level 100 access')
            
           
        def user_added(*args,**kwargs):
            chan = kwargs.get('chan')
            user = kwargs.get('user')
            level = kwargs.get('level')
           
            self.access_level_pass(users=chan.users,channel=chan)
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'User %s added to %s access list at level %s' % (user['username'],chan.uid,level))

        def user_deleted(*args,**kwargs):
            chan = kwargs.get('chan')
            user = kwargs.get('user')

            self.access_level_pass(users=chan.users,channel=chan)
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'User %s deleted from %s access list ' % (user['username'],chan.uid))
       
                
        if pseudoclient_uid != self.factory.enforcer.uid:
            return
        
        try:
        
            lx = message.split(' ')
          
            if len(lx) == 4:
                channel_name,function,string,value = lx
                value = int(value)
                
            elif len(lx) == 3:
                channel_name,function,string = lx
                value = -1
            else:
                usage()
                return
                
            function = function.upper()
            channel_name = channel_name.lower()
            
            if function not in ('ADD','DEL','LIST'):
                raise ValueError('Invalid Type')
       
        except ValueError:
            usage()
            return
        
       
        # First make sure the channel name is valid
        if not channel_name.startswith('#'):
            usage()
            return 
   
        chan = self.protocol.lookup_uid(channel_name)
        user = self.protocol.lookup_uid(source_uid)
        # Make sure the channel exists
        if not chan:
            no_channel(chan.uid)
            return
        
        if not user:
            usage()
            return
       
        
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_channel_accesslist = yield self.factory.db.runInteraction(self.sqe.get_channel_accesslist,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        
        if not db_channel:
            usage()
            return     
            
            
            
        # If user is not the channel founder, proceed to more rigorous access checks
        if db_channel['founder_id'] != db_user['id']:
            
            if db_user['id'] not in db_channel_accesslist:
                access_denied()
                return
                
            access = db_channel_accesslist[db_user['id']].get('access_level',0)

            
            if access < db_channel['level_settings']:
                access_denied()
                return
        else:
            access = 101
        
       
        cfg = self.factory.cfg.sqlextension 
        if function in ('ADD','DEL'):
            db_add_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,string)
            
            if not db_add_user:
                no_user(string)
                return
            
            if db_add_user['id'] == db_channel['founder_id']:
                no_founder()
                return
            
            if function == 'ADD':
                if value >= access:
                    too_high()
                    return
                self.factory.db.runOperation \
                (
                    "INSERT INTO " + cfg.table_prefix + "_channel_access"
                    " (channel_id,user_id,access_level)"
                    " VALUES (%s,%s,%s)"
                    " ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id), user_id = VALUES(user_id), access_level = VALUES(access_level)", 
                    [db_channel['id'],db_add_user['id'],value]
                ).addCallbacks(user_added,self.query_error_callback,None,{'chan': chan, 'user': db_add_user, 'level': value})
            
            elif function == 'DEL':
                if value >= access:
                    too_high()
                    return
                self.factory.db.runOperation \
                (
                    "DELETE FROM " + cfg.table_prefix + "_channel_access"
                    " WHERE channel_id = %s AND user_id = %s LIMIT 1", 
                    [db_channel['id'],db_add_user['id']]
                ).addCallbacks(user_deleted,self.query_error_callback,None,{'chan': chan, 'user': db_add_user})
            else:
                usage()
                return
                
        elif function == 'LIST':
           
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,'Access List for %s:' % (chan.uid))
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,(tools.pad('  Nick' ,30) + ' Access Level'))
            # Show founder since it doesn't actually exist in the db
            self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,(tools.pad('  %s' % db_channel['founder_name'],30) + ' %s' % 100))

            for name,value in db_channel_accesslist.items():
                
                self.protocol.st_send_command('NOTICE',[source_uid],pseudoclient_uid,(tools.pad('  %s' % value.get('username'),30) + ' %s' % value.get('access_level',0)))


            
    @defer.inlineCallbacks    
    def ps_privmsg_register(self,source_uid,command,message,pseudoclient_uid):
        """
            Usage:          REGISTER #channel
            Access:         CHANNEL OPERATOR ONLY
            Description:    Registers you as the founder of an unregistered channel.
                            This allows you to set persistent access levels, 
                            forced modes, topics and more.
        """
        
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
        
        channel = message
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
            
        
        
        db_channel = yield self.factory.db.runInteraction(self.sqe.get_channel_details,chan.uid)
        db_user = yield self.factory.db.runInteraction(self.sqe.get_user_complete,user.nick)
        
        if not db_user:
            self.kill_user(user.nick)
            return
        

        if not db_channel and db_user:
        
            # Check to see if the user is an OP on that channel
            if not chan.user_has_mode(user,'o'):
                access_denied()
                return
            
            cfg = self.factory.cfg.sqlextension
            self.factory.db.runOperation \
            (
                "INSERT INTO " + cfg.table_prefix + "_channels (name,founder_id) VALUES (%s,%s)", 
                [chan.uid,db_user['id']]
            ).addCallbacks(channel_added,self.query_error_callback,None,{'chan': chan, 'db_user': db_user, 'founder': user})
            
        else:
        
            already_registered()
            return

