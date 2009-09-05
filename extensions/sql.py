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
    
    def __init__(self,*args,**kwargs):
        super(self.__class__, self).__init__(*args,**kwargs)
        
        self.factory.pending_channels = {}
        self.factory.pending_users = {}
        

        
        
        try:
            self.log.log(cll.level.VERBOSE,'Initializing DB connection pool...')
            
            sql_cfg = self.factory.cfg.sqlextension
            
            # Setup db connection using config-specified values here
            self.factory.db = adbapi.ConnectionPool \
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
            self.factory.quit()
            

   
    
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
        Callback method for testing of queries. Simply prints
        the query output to the console.
    """
    def print_result(self,r):
        if r:
            self.loglog(cll.level.INFO,pformat(r))
        else:
            self.log.log(cll.level.INFO,'No Rows Returned')
        return True
    
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
        
        cfg = self.factory.cfg.sqlextension
        
        self.factory.db.runOperation \
            (
                "UPDATE " + cfg.table_prefix + "_users"
                " SET last_quit = NOW(), last_quit_message = %s"
                " WHERE id = %s LIMIT 1", 
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
        d.addCallbacks(self.update_local_user_from_db,self.user_update_clear_pending,[],{'user': user})
        d.addCallbacks(self.user_update_clear_pending,self.user_update_clear_pending,[],{'user': user})
        
        self.factory.pending_users[user.uid] = d
        self.factory.pending_users[user.uid].callback(None)

        
            
        
    """
        Gets a users' details from the SQL database.
        Returns a deferred for use with callbacks.
    """
    def get_user(self,name):
        # We always set cfg as a local variable before the query for ease of use, but 
        # it *CANNOT* be a class wide thing because then config rehashes would not be 
        # propagated correctly
        cfg = self.factory.cfg.sqlextension
        
        return self.factory.db.runQuery \
            (
                " SELECT"
                " r.id as db_id, r.level as db_level, r.approved as db_approved,"
                " (SELECT"
                    " GROUP_CONCAT(c.name SEPARATOR ',')"
                    " FROM " 
                        " " + cfg.table_prefix + "_user_autojoin a,"
                        " " + cfg.table_prefix + "_channels c"
                    " WHERE a.user_id = r.id AND a.channel_id = c.id ORDER BY c.name ASC"
                " ) as autojoin"
                " FROM " + cfg.table_prefix + "_users r"
                " WHERE username = %s LIMIT 1",name
            )
            

    def get_channel_modes(self,name):
        cfg = self.factory.cfg.sqlextension
        return self.factory.db.runQuery \
            (
            
                " SELECT "
                    " m.id as db_id, m.mode as db_mode, m.value as db_value"
                " FROM " + cfg.table_prefix + "_channels c" 
                " INNER JOIN " + cfg.table_prefix + "_channel_modes m"
                " ON (c.id = m.channel_id)"
                " WHERE c.name = %s LIMIT 1",name
                
            )
               
               
    def get_channel(self,name):	
        cfg = self.factory.cfg.sqlextension
        return self.factory.db.runQuery \
            (
            
                " SELECT "
                    " c.id as db_id, c.founder_id as db_founder_id, c.topic as db_topic,"
                    " c.type as db_type, c.min_level as db_min_level,"
                    " c.level_voice as db_level_voice, c.level_halfop as db_level_halfop,"
                    " c.level_op as db_level_op, c.level_superop as db_level_superop,"
                    " u.username as db_founder_name" 
                " FROM " + cfg.table_prefix + "_channels c" 
                " LEFT JOIN " + cfg.table_prefix + "_users u"
                " ON (c.founder_id = u.id)"
                " WHERE c.name = %s LIMIT 1",name
                
            )

            
    def get_channel_access_list(self,name):
        cfg = self.factory.cfg.sqlextension
        return self.factory.db.runQuery \
            (
            
                " SELECT "
                    " a.user_id, a.access_level"
                " FROM " + cfg.table_prefix + "_channel_access a," 
                " " + cfg.table_prefix + "_channels c" 
                " WHERE c.name = %s AND c.id = channel_id ORDER BY a.access_level DESC",name
                
            )       
            
            
    def st_receive_fjoin(self,timestamp,channel,users,modes):

        channel_uid = self.protocol.lookup_uid(channel)
        
        if not channel_uid:
            self.log.log(cll.level.ERROR,'We received a hook FJOIN but the channel could not be looked up by UID :wtc:')
            return
            
                    
        if self.factory.is_bursting:

            # This is a BURST FJOIN. We want to load all the info
            # we can for this channel locally and then we have to
            # make less queries later. We save the defer into a
            # pending list so we can add callbacks from functions 
            # requiring this data to be updated before they can 
            # be executed.
            
            d = defer.Deferred()
            d.addCallback(lambda x: self.get_channel(channel))
            
            d.addCallbacks(self.update_local_channel_from_db,self.channel_update_clear_pending,[],{'channel': channel_uid})
            d.addCallback(lambda y: self.get_channel_access_list(channel))
            
            d.addCallbacks(self.update_local_channel_modes_from_db,self.channel_update_clear_pending,[],{'channel': channel_uid})
            d.addCallbacks(self.channel_update_clear_pending,self.channel_update_clear_pending,[],{'channel': channel_uid})
      
            
            self.factory.pending_channels[channel_uid.uid] = d
            self.factory.pending_channels[channel_uid.uid].callback(None)


            
    
    def update_local_channel_modes_from_db(self,result,**kwargs):
        channel_uid = kwargs.get('channel')
        if not result:
            # Channel is not registered, so ignore it
            return
        

            
         
    def channel_update_clear_pending(self,result,**kwargs):
        channel_uid = kwargs.get('channel')
        
        if channel_uid:
            if channel_uid.uid in self.factory.pending_channels:
                del self.factory.pending_channels[channel_uid.uid]
                
        return True

     
     
    """
        This is called back when a channel update
        SQL query completes. It updates a local channel
        object with data from the database and 
    """
    def update_local_channel_from_db(self,result,**kwargs):
        if result:
            channel_uid = kwargs.get('channel')
            # This should only ever contain 1 channel but the for allows us
            # to un-listify result without creating a new var
            for db_channel in result:
                channel_uid.update_from(db_channel)
            
        return True
            

       
       
    """
        This is called back when a channel update
        SQL query completes. It updates a local channel
        object with data from the database and 
    """
    def update_local_channel_modes_from_db(self,result,**kwargs):
       
        if result:
            channel_uid = kwargs.get('channel')
            # This should only ever contain 1 channel but the for allows us
            # to un-listify result without creating a new var
      
            for aline in result:
                channel_uid.access[int(aline.get('user_id',0))] = int(aline.get('access_level',0))
           
        return True


    """ 
        Clear lookup errors from the pending list
        too so we can continue to work on them even though
        they have no DB records.
    """
    def user_update_clear_pending(self,*args,**kwargs):
     
        user = kwargs.get('user')
        if user:
            if user.uid in self.factory.pending_users:
                del self.factory.pending_users[user.uid]
        
        return True

    def update_local_user_from_db(self,result,**kwargs):
       
        if result:
            user_uid = kwargs.get('user')
            
            # This should only ever contain 1 user but the for allows us
            # to un-listify result without creating a new var
            for db_user in result:
                user_uid.update_from(db_user)
                
                    
                cfg = self.factory.cfg.sqlextension
                self.factory.db.runOperation \
                    (
                    
                        " UPDATE " + cfg.table_prefix + "_users"
                        " SET ip = %s, last_login = %s WHERE id = %s LIMIT 1", 
                        [user_uid.ip,user_uid.timestamp,user_uid.db_id]
                        
                    ).addCallbacks(self.query_update_callback,self.user_update_clear_pending,{'user_uid': user_uid})
                    
        return True
        

   
    
    
