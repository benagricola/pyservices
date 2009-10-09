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
                
            self.factory.add_hook('quit',self)
            
        except Exception, e:
            self.log.log(cll.level.ERROR,'Error trying to initialize DB connection pool (%s)' % e)
            self.factory.quit()
            
    def quit(self):
        self.factory.db.finalClose()
        
            
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
        Called during a netburst or new client introduction,
        this function attempts to update user
        details in the SQL database.
    """
    def st_receive_uid(self,**kwargs):
        user = kwargs.get('user')
        
        
        if not user:
            self.log.log(cll.level.ERROR,'Did not receive expected args from main method.')
            return 
      
        cfg = self.factory.cfg.sqlextension
        self.factory.db.runOperation \
            (
            
                " UPDATE " + cfg.table_prefix + "_users"
                " SET ip = %s, last_login = %s WHERE username = %s LIMIT 1", 
                [user.ip,user.timestamp,user.nick]
                
            ).addCallbacks(self.query_update_callback,self.query_error_callback)
        
        
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
                " WHERE username = %s LIMIT 1", 
                [kwargs.get('reason'),user.nick]
            ).addCallbacks(self.query_update_callback,self.query_error_callback)

    
    """
        Gets multiple users' details from the SQL database.
        Returns a deferred for use with callbacks.
    """
    def get_users_complete(self,trans,names):
        # We always set cfg as a local variable before the query for ease of use, but 
        # it *CANNOT* be a class wide thing because then config rehashes would not be 
        # propagated correctly
        cfg = self.factory.cfg.sqlextension
            
        format = ','.join(['%s'] * len(names))
        trans.execute \
        (
            " SELECT"
            " r.id as id, r.username as username, r.level as level,"
            " r.approved as approved, r.bitmask as bitmask,"
            " (SELECT"
                " GROUP_CONCAT(c.name SEPARATOR ',')"
                " FROM " 
                    " " + cfg.table_prefix + "_user_autojoin a,"
                    " " + cfg.table_prefix + "_channels c"
                " WHERE a.user_id = r.id AND a.channel_id = c.id ORDER BY c.name ASC"
            " ) as autojoin"
            " FROM " + cfg.table_prefix + "_users r"
            " WHERE username IN (%s)" % format,tuple(names)
        )
        
        return dict([(x['username'],x) for x in trans.fetchall()])
       
        
    """
        Gets a users' details from the SQL database.
    """
    def get_user_complete(self,trans,name):
        cfg = self.factory.cfg.sqlextension
       
        trans.execute \
        (
            " SELECT"
            " r.id as id, r.username as username, r.level as level,"
            " r.approved as approved, r.bitmask as bitmask,"
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
        
        return trans.fetchone()
         

            
    def get_channel_details(self,trans,name):
        cfg = self.factory.cfg.sqlextension
        trans.execute \
        (   " SELECT "
                " c.id as id, c.founder_id as founder_id, c.topic as topic,"
                " c.topic_protection as topic_protection, c.type as type," 
                " c.min_level as min_level, c.level_voice as level_voice,"
                " c.level_halfop as level_halfop, c.level_op as level_op,"
                " c.level_superop as level_superop,"
                " c.level_settings as level_settings,"
                " c.bit as bit,"
                " u.username as founder_name,"
                " c.channel_mode_protection as channel_mode_protection,"
                " c.user_mode_protection as user_mode_protection"
            " FROM " + cfg.table_prefix + "_channels c" 
            " LEFT JOIN " + cfg.table_prefix + "_users u"
            " ON (c.founder_id = u.id)"
            " WHERE c.name = %s LIMIT 1",name
        )
        return trans.fetchone()
    
    def get_channel_accesslist(self,trans,name):
        cfg = self.factory.cfg.sqlextension
        trans.execute \
        (    
            " SELECT "
                " a.user_id, a.access_level, u.username"
            " FROM " + cfg.table_prefix + "_channel_access a," 
            " " + cfg.table_prefix + "_channels c,"
            " " + cfg.table_prefix + "_users u"             
            " WHERE c.name = %s AND c.id = a.channel_id AND u.id = a.user_id ORDER BY a.access_level DESC",name
        )
       
        
        return dict([(x['user_id'],{'username': x['username'] ,'access_level': x['access_level']}) for x in trans.fetchall()])
       
            
    def get_channel_modes(self,trans,name): 
        cfg = self.factory.cfg.sqlextension
        trans.execute \
        (
        
            " SELECT "
                " m.id as id, m.mode as mode, m.value as value"
            " FROM " + cfg.table_prefix + "_channels c" 
            " INNER JOIN " + cfg.table_prefix + "_channel_modes m"
            " ON (c.id = m.channel_id)"
            " WHERE c.name = %s",name
            
        )
        
        return dict([(x['mode'],x['value']) for x in trans.fetchall()])
 
        
    def get_channel_complete(self,trans,name):

        return \
        [
            self.get_channel_details(trans,name),
            self.get_channel_accesslist(trans,name),
            self.get_channel_modes(trans,name),
        ]
   
       
    

   
    
    
