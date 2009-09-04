"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

from datetime import datetime as datetime
from MySQLdb import cursors as cursors
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
class SQLExtension(ext.BaseExtension):
    
    def __init__(self,receiver):
        
        self.pending_channels = {}
        self.pending_users = {}
        
        super(SQLExtension, self).__init__(receiver)
        
        try:
            self.log.log(cll.level.VERBOSE,'Initializing DB connection pool...')
            
            sql_cfg = self.receiver.factory.cfg.sqlextension
            
            # Setup db connection using config-specified values here
            self.db = adbapi.ConnectionPool \
                                        (
                                            "MySQLdb", 	
                                            host=sql_cfg.db_host, 
                                            port=sql_cfg.db_port, 
                                            db=sql_cfg.db_name, 
                                            user=sql_cfg.db_username,
                                            passwd=sql_cfg.db_password, 
                                            cursorclass=cursors.DictCursor,
                                            cp_reconnect=True,
                                        )
            
        except Exception, e:
            self.log.log(cll.level.ERROR,'Error trying to initialize DB connection pool (%s)' % e)
            self.receiver.quit()
            
        # Add non-automatic hooks here
        self.receiver.add_hook('quit',self)
    
    
    """
        Hooks into the st_send_burst method allowing the extension to insert 
        its own pseudo-client UID's into the burst. This allows us to fake 
        network clients for the purposes of services.
    """
    def st_send_burst(self):
        cfg_enforcer = self.receiver.factory.cfg.sqlextension.services.enforcer
        cfg_oper_tool = self.receiver.factory.cfg.sqlextension.services.oper_tool
        cfg_global_announce = self.receiver.factory.cfg.sqlextension.services.global_announce
        
        self.enforcer = self.receiver.st_add_pseudoclient(cfg_enforcer.nick,cfg_enforcer.host,cfg_enforcer.ident,'+iow',cfg_enforcer.realname,self)
        self.oper_tool = self.receiver.st_add_pseudoclient(cfg_oper_tool.nick,cfg_oper_tool.host,cfg_oper_tool.ident,'+iow',cfg_oper_tool.realname,self)
        self.global_announce = self.receiver.st_add_pseudoclient(cfg_global_announce.nick,cfg_global_announce.host,cfg_global_announce.ident,'+iow',cfg_global_announce.realname,self)
        
    
    """
        Hooks into the quit method (which is manually called) and 
        sends a global services notice depending on config settings.
        Also closes the database connection established in __init__()
    """
    def quit(self):
        if self.receiver.factory.cfg.sqlextension.services.global_status_messages:
            self.send_global_notice(self.receiver.factory.cfg.sqlextension.services.global_status_disconnect)
        self.db.finalClose()
        
    
    """
        Hooks into the endburst received during connection
        phase (main function only calls the hook during connection
        for this reason) and fires a global services notice depending
        on config settings.
    """
    def st_receive_endburst(self,prefix,args):
        #reactor.callLater(10, self.handle_burst_data)
        
        if self.receiver.factory.cfg.sqlextension.services.global_status_messages:
            self.send_global_notice(self.receiver.factory.cfg.sqlextension.services.global_status_connect)
        
    """ 
        Sends a global notice from the announcer pseudoclient 
        set in st_send_burst().
    """
    def send_global_notice(self,message):
        self.receiver.st_send_command('NOTICE',['$*'],self.global_announce.uid,message)
    
    
    """ 
        This method is called when a runOperation callback
        is required. All it does is debug log that the 
        query completed successfully.
    """
    def query_update_callback(self,*args,**kwargs):
        self.log.log(cll.level.DATABASE,'Query OK')
    
    
    """ 
        This method is called when an SQL query returns an
        error. It logs the error and then attempts to 
        exit the application via the receivers' quit() method.
    """
    def query_error_callback(self,error):
        self.log.log(cll.level.DATABASE,'Query encountered error: %s' % error.value)
    
        
    
    """
        Callback method for testing of queries. Simply prints
        the query output to the console.
    """
    def print_result(self,r):
        if r:
            self.loglog(cll.level.INFO,pformat(r))
        else:
            self.log.log(cll.level.INFO,'No Rows Returned')
    
    
    """
        Not Implemented (yet)
    """
    def st_receive_version(self,**kwargs):
        pass		
     

    """
        Called on a quit, it updates the SQL database with the 
        users' last quit message and quit time.
    """
    def st_receive_quit(self,**kwargs):
        user = kwargs.get('user')
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
        
    
        self.db.runOperation(
                            "UPDATE " + self.receiver.factory.cfg.sqlextension.table_prefix + "_users SET last_quit = NOW(), last_quit_message = %s WHERE id = %s LIMIT 1", 
                            [kwargs.get('reason'),user.db_id]
                            ).addCallbacks(self.query_update_callback,self.query_error_callback)
        
       
    """
        Called during a netburst or new client introduction,
        this function attempts to query + update user
        details from the SQL database and places the user 
        UID into a pending_users table so functions that rely
        on updated data will be halted until the query completes.
    """
    def st_receive_uid(self,**kwargs):
        user = kwargs.get('user')
        
        
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
            
        d = defer.Deferred()
        d.addCallback(lambda x: self.get_user(user.nick))
        d.addCallbacks(self.update_local_user_from_db,self.user_update_error,[user])
        d.addCallbacks(self.user_update_complete,self.user_update_error,[user])
        
        self.pending_users[user.uid] = d
        self.pending_users[user.uid].callback(None)

        
            
    def registration_help(self,channel,user):
        print "REGISTRATION HELP"
        
        
    """
        Gets a users' details from the SQL database.
        Returns a deferred for use with callbacks.
    """
    def get_user(self,name):
        return self.db.runQuery(
                            " SELECT"
                            " r.id as db_id, r.level as db_level, r.approved as db_approved,"
                            " (SELECT"
                                " GROUP_CONCAT(c.name SEPARATOR ',')"
                                " FROM " 
                                    " " + self.receiver.factory.cfg.sqlextension.table_prefix + "_user_autojoin a,"
                                    " " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels c"
                                " WHERE a.user_id = r.id AND a.channel_id = c.id ORDER BY c.name ASC"
                            " ) as autojoin"
                            " FROM " + self.receiver.factory.cfg.sqlextension.table_prefix + "_users r"
                            " WHERE username = %s LIMIT 1",name
                            )
            
      

    """
        Called on a timeout after a ban, this
        function unbans a given banmask on a 
        channel using the enforcer UID set 
        during net burst.
    """
    def do_unban(self,*args,**kwargs):
        channel = kwargs.get('channel')
        banmask = kwargs.get('banmask')

        self.receiver.st_send_command('SVSMODE',[channel.uid,'-b',banmask],self.enforcer.uid)
        self.log.log(cll.level.DEBUG,'Unbanned %s on %s (Timeban Expiry)' % (banmask,channel.uid))
   
        
        
    """
        This function enforces modes for a specific user
        on a specific channel using either their global
        access level or their access level on that channel,
        depending on the channel type.
    """
    def enforce_modes(self,*args,**kwargs):
        cfg_enforcer = self.receiver.factory.cfg.sqlextension.services.enforcer
        
        user = kwargs.get('user')
        channel = kwargs.get('channel')
        public = kwargs.get('public',False)
        
        _d = None
        _r = None
        

        # If channel update for this is pending ,add a callback to the pending method
        if channel.uid in self.pending_channels: 
            _d = self.pending_channels.get(channel.uid).addCallback(getattr(self,tools.called_by(1)),**kwargs)
            
            
        # If user update for this is pending, add a callback to the pending method
        # AND if there was also a channel update pending, then chain them.
        if user.uid in self.pending_users:
            _r = self.pending_users.get(user.uid).addCallback(getattr(self,tools.called_by(1)),**kwargs)
            if _d:
                _d.chainDeferred(_r)
                
        if _d or _r:
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
            
            self.receiver.st_send_command('SVSMODE',[channel.uid,'-o+b',user.uid,banmask],self.enforcer.uid)
            self.receiver.st_send_command('SVSPART',[user.uid,channel.uid],self.enforcer.uid)
            self.receiver.st_send_command('NOTICE',[user.uid],self.enforcer.uid,'Access to %s denied by user level (%s < %s). You have been banned for %ss' % (channel.uid,effective_level,channel.db_min_level,cfg_enforcer.ban_accessdenied_expiry))
            
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
        self.receiver.st_send_command('SVSMODE',[channel.uid,give + take,give_user,take_user],self.enforcer.uid)
    
    
    def access_level_pass(self,users,channel):
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
                    
            
            
    def handle_burst_data(self):
        for users, channel in self.pending_channels:
            self.access_level_pass(users,channel)
            
        
    
    def get_channel_modes(self,name):
        return self.db.runQuery \
            (
            
                " SELECT "
                    " m.id as db_id, m.mode as db_mode, m.value as db_value"
                " FROM " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels c" 
                " INNER JOIN " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channel_modes m"
                " ON (c.id = m.channel_id)"
                " WHERE c.name = %s LIMIT 1",name
                
            )
                        
    def get_channel(self,name):	
        return self.db.runQuery \
            (
            
                " SELECT "
                    " c.id as db_id, c.founder_id as db_founder_id, c.topic as db_topic,"
                    " c.type as db_type, c.min_level as db_min_level,"
                    " c.level_voice as db_level_voice, c.level_halfop as db_level_halfop,"
                    " c.level_op as db_level_op, c.level_superop as db_level_superop,"
                    " u.username as db_founder_name" 
                " FROM " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels c" 
                " LEFT JOIN " + self.receiver.factory.cfg.sqlextension.table_prefix + "_users u"
                " ON (c.founder_id = u.id)"
                " WHERE c.name = %s LIMIT 1",name
                
            )

    def get_channel_access_list(self,name):
        return self.db.runQuery \
            (
            
                " SELECT "
                    " a.user_id, a.access_level"
                " FROM " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channel_access a," 
                " " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels c" 
                " WHERE c.name = %s AND c.id = channel_id ORDER BY a.access_level DESC",name
                
            )       
                
    def st_receive_fjoin(self,timestamp,channel,users,modes):

        channel_uid = self.receiver.lookup_uid(channel)
        
        if not channel_uid:
            self.log.log(cll.level.ERROR,'We received a hook FJOIN but the channel could not be looked up by UID :wtc:')
            return
            
                    
        if not self.receiver.factory.is_bursting:
        
            # This does not appear to be a BURST FJOIN on connect,
            # so we will proceed with checking the channel to see
            # if it is registered.
            # By the time initial burst is over, there should be no
            # need to defer access level scanning based on pending
            # SQL queries, so just run it straight away.
            self.access_level_pass(users,channel_uid)
        
        else:
    
            # This is a BURST FJOIN. We want to load all the info
            # we can for this channel locally and then we have to
            # make less queries later. We save the defer into a
            # pending list so we can add callbacks from functions 
            # requiring this data to be updated before they can 
            # be executed.
            
            d = defer.Deferred()
            d.addCallback(lambda x: self.get_channel(channel))
            d.addCallbacks(self.update_local_channel_from_db,self.channel_update_error,[channel_uid])
            
            
            
            e = defer.Deferred()
            e.addCallback(lambda y: self.get_channel_access_list(channel))
            e.addCallbacks(self.update_local_channel_modes_from_db,self.channel_update_error,[channel_uid])
            e.addCallbacks(self.channel_update_complete,self.channel_update_error,[channel_uid])
            d.chainDeferred(e)
            
            self.pending_channels[channel_uid.uid] = d
            self.pending_channels[channel_uid.uid].callback(None)

            
            
    
    def update_local_channel_modes_from_db(self,result,channel_uid):
        if not result:
            # Channel is not registered, so ignore it
            return
        

            
         
    def channel_update_complete(self,result,channel_uid):
        if channel_uid.uid in self.pending_channels:
           
            del self.pending_channels[channel_uid.uid]

       
        self.access_level_pass(channel_uid.users,channel_uid)
        return True
     
     
    def channel_update_error(self,result,channel_uid):
        if channel_uid.uid in self.pending_channels:
           
            del self.pending_channels[channel_uid.uid]
            
        return True
     
    """
        This is called back when a channel update
        SQL query completes. It updates a local channel
        object with data from the database and 
    """
    def update_local_channel_from_db(self,result,channel_uid):
        if result:
    
            # This should only ever contain 1 channel but the for allows us
            # to un-listify result without creating a new var
            for db_channel in result:
                channel_uid.update_from(db_channel)
            
            return True
            
        else: 
            return False
            
    """
        This is called back when a channel update
        SQL query completes. It updates a local channel
        object with data from the database and 
    """
    def update_local_channel_modes_from_db(self,result,channel_uid):
       
        if result:
            # This should only ever contain 1 channel but the for allows us
            # to un-listify result without creating a new var
      
            for aline in result:
                channel_uid.access[int(aline.get('user_id',0))] = int(aline.get('access_level',0))
           
            return True
            
        else: 
            return False
       

    def user_update_complete(self,result,user_uid):
        if user_uid.uid in self.pending_users:
            del self.pending_users[user_uid.uid]
           
        # Do autojoins here
        if hasattr(user_uid,'autojoin'):
            if user_uid.autojoin:
                for chan in user_uid.autojoin.split(','):
                    self.receiver.st_send_command('SVSJOIN',[user_uid.uid,chan],self.receiver.factory.cfg.server.sid)
                    
            
    """ 
        Clear lookup errors from the pending list
        so we can continue to work on them even though
        they have no DB records.
    """
    def user_update_error(self,result,user_uid):

        if user_uid.uid in self.pending_users:
           
            del self.pending_users[user_uid.uid]
           
           
    def update_local_user_from_db(self,result,user_uid):
       
        if result:
          
            # This should only ever contain 1 user but the for allows us
            # to un-listify result without creating a new var
            for db_user in result:
                user_uid.update_from(db_user)
                if not self.receiver.factory.is_bursting:
                    self.receiver.st_send_command('NOTICE',[user_uid.uid],self.enforcer.uid,'Welcome %s! Your current global access level is %s.' % (user_uid.nick,user_uid.db_level))
                    
                self.db.runOperation \
                    (
                    
                        " UPDATE " + self.receiver.factory.cfg.sqlextension.table_prefix + "_users"
                        " SET ip = %s, last_login = %s WHERE id = %s LIMIT 1", 
                        [user_uid.ip,user_uid.timestamp,user_uid.db_id]
                        
                    ).addCallbacks(self.query_update_callback,self.user_update_error,{'user_uid': user_uid})
                    
        return None
        
        
    def ps_privmsg_global(self,source_uid,command,message,pseudoclient_uid):
        if pseudoclient_uid == self.oper_tool.uid: 
            source = self.receiver.lookup_uid(source_uid)
        
            if not source:
                self.log.log(cll.level.ERROR,'Could not find existing entry for source UID %s' % source_uid)
                return False
            
            if 'o' in source.modes and source.oper_type is not None:
                self.send_global_notice('[%s]: %s' % (source.nick,message))
            return True
    
    
    def ps_privmsg_chanlevel(self,command,message,pseudoclient_uid,source_uid):
        """
            Access: 		FOUNDER ONLY
            Usage:  		CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100> 
            Description:	Sets the minimum levels on a channel to be automatically 
                            granted access, voice, halfop, op, or protected op respectively.
        """
        
        def usage():
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] (USERLEVEL) Usage: CHANLEVEL #channel MIN|VOICE|HOP|OP|SOP <1-100>')
            
        def no_change(chan,type,level):
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s already has %s access level of %s' % (chan,type,level))
            
        def access_denied():
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def level_updated(*args,**kwargs):
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s %s access level set to: %s' % (kwargs.get('chan'),kwargs.get('type'),kwargs.get('level')))
            
        def conflicting_mode(*args):
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[ERROR] %s level (%s) may not be below that of %s (%s)' % args)
            
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
        
        channel = self.receiver.lookup_uid(channel_name)
        user = self.receiver.lookup_uid(source_uid)
            
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
            
            
        self.db.runOperation \
            (
                "UPDATE " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels SET " + db_field + " = %s WHERE id = %s LIMIT 1", 
                [new_level,channel.db_id]
            ).addCallbacks(level_updated,self.query_error_callback,None,{'chan': channel.uid,'type': type, 'level': new_level})
        
        self.access_level_pass(channel.users,channel)
        
        return False
        
            
    def ps_privmsg_chantype(self,command,message,pseudoclient_uid,source_uid):
        """
            Access: 		FOUNDER ONLY
            Usage:  		CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST
            Description:	Sets the type of channel for authentication purposes.
            
                            USERLEVEL: 	modes + access given to a user are based on their 
                                        global user level and the CHANLEVEL settings of 
                                        the named channel.
                            ACCESSLIST:	modes + access given to a user are based on the 
                                        access list maintained by the founder of the channel.
                            PUBLIC_:	Specifying this before either of these two types 
                                        of channel allows public access to the channel 
                                        (any level user may join), and only modes given 
                                        are defined by the channel type.
        """
        
        def usage():
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] Syntax: CHANTYPE #channel [PUBLIC_]USERLEVEL|ACCESSLIST')
        
        def no_change(chan,type):
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s already has type %s' % (chan,type))
        
        def access_denied():
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'[FOUNDER ONLY] <---- READ THIS (Access Denied)')
            
        def type_updated(*args,**kwargs):
            self.receiver.st_send_command('PRIVMSG',[source_uid],pseudoclient_uid,'Channel %s type changed to: %s' % (kwargs.get('chan'),kwargs.get('type')))
            
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
        
        channel = self.receiver.lookup_uid(channel_name)
        user = self.receiver.lookup_uid(source_uid)
            
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
        
        self.db.runOperation \
            (
                "UPDATE " + self.receiver.factory.cfg.sqlextension.table_prefix + "_channels SET type = %s WHERE id = %s LIMIT 1", 
                [channel.db_type,channel.db_id]
            ).addCallbacks(type_updated,self.query_error_callback,None,{'chan': channel.uid,'type': channel.db_type})
        
        self.access_level_pass(channel.users,channel)
        
        return False
        
        
    def ps_privmsg_register(self,source_uid,command,message,pseudoclient_uid):
        self.receiver.st_send_command('PRIVMSG',[source_uid.uid],pseudoclient_uid,'Registering %s' % str(message))
        return True
        