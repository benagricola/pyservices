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
class SQLGlobal(ext.BaseExtension):
    
    required_extensions = ['SQLExtension']
    global_announce = None
        
    def __init__(self,*args,**kwargs):

        super(self.__class__, self).__init__(*args,**kwargs)

        if not hasattr(self.factory,'global_announce') or not self.factory.global_announce:
            self.create_global_announce()
            
       
        self.factory.add_hook('quit',self)
        
        
    def create_global_announce(self):
        cfg_global_announce = self.factory.cfg.sqlextension.services.global_announce
        self.factory.global_announce = self.protocol.st_add_pseudoclient(cfg_global_announce.nick,cfg_global_announce.host,cfg_global_announce.ident,'+iow',cfg_global_announce.realname,self)
        
        
    """
        Hooks into the st_send_burst method allowing the extension to insert 
        its own pseudo-client UID's into the burst. This allows us to fake 
        network clients for the purposes of services.
    """
    def st_send_burst(self):
        pass
    
    """
        Hooks into the endburst received during connection
        phase (main function only calls the hook during connection
        for this reason) and fires a global services notice depending
        on config settings.
    """
    def st_receive_endburst(self,prefix,args):
        #reactor.callLater(10, self.handle_burst_data)
        
        if self.factory.cfg.sqlextension.services.global_status_messages:
            self.send_global_notice(self.factory.cfg.sqlextension.services.global_status_connect)
      

    """ 
        Sends a global notice from the announcer pseudoclient 
        set in st_send_burst().
    """
    def send_global_notice(self,message):
        self.protocol.st_send_command('NOTICE',['$*'],self.factory.global_announce.uid,message)
    
    
    """
        Hooks into the quit method (which is manually called) and 
        sends a global services notice depending on config settings.
        Also closes the database connection established in __init__()
    """
    def quit(self):
        if self.factory.cfg.sqlextension.services.global_status_messages:
            self.send_global_notice(self.factory.cfg.sqlextension.services.global_status_disconnect)
        self.factory.db.finalClose()
        
        
    # !!! FIX: This should be a part of operserve but is also related to global
    def ps_privmsg_global(self,source_uid,command,message,pseudoclient_uid):
        if pseudoclient_uid == self.oper_tool.uid: 
            source = self.protocol.lookup_uid(source_uid)

            if not source:
                self.log.log(cll.level.ERROR,'Could not find existing entry for source UID %s' % source_uid)
                return False
            
            if 'o' in source.modes and source.oper_type is not None:
                self.send_global_notice('[%s]: %s' % (source.nick,message))
            return True
