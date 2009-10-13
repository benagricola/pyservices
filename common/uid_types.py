"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 PyServices Development Team	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

from datetime import datetime as datetime
import common.tools as tools

class Unique(object):
    
    
    def __init__(self,uid):
        self.uid = uid
        self._modes = {}
        
    def update_from(self,dict):
        for a,v in dict.iteritems():
                setattr(self,a,v) 
        

    def modes_return_parsed(self):
        _modes = ['+',]
        _params = []
        
        for k,v in self._modes.iteritems():
            _modes.append(k)
            if v:
                _params.append(v) 
        
        if _params:
            _params = ' '.join(_params)
        else:
            _params = ''
            
        return (''.join(_modes),_params)
        
        
class Server(Unique):
    
    
    def __init__(self,uid):
        Unique.__init__(self,uid) 
        self.name = ''
        self.password = ''
        self.description = ''
        self.hops = 0
        self.users = []
        
        
class User(Unique):
    

    def __init__(self,uid):
        Unique.__init__(self,uid) 
        
        
        self.nick = ''
        
        self.hostname = ''
        self.displayed_hostname = ''
        
        self.ident = ''
        self.ip = ''
        
        self.signed_on = ''
        
        self.gecos = ''
        
        self._timestamp = tools.timestamp()
        self._metadata = {}
        self._channels = {}
    
    def timestamp_get(self):
        return self._timestamp
    
    def timestamp_set(self,timestamp):
        self._timestamp = datetime.fromtimestamp(int(timestamp))
    
    def timestamp_del(self):
        self.timestamp = tools.timestamp()
        
    timestamp = property(timestamp_get,timestamp_set,timestamp_del)
    
    def metadata_get(self):
        return self._metadata
    
    def metadata_set(self,metadata):
        self._metadata.update(metadata)
    
    def metadata_del(self):
        self._metadata = {}
        
    metadata = property(metadata_get,metadata_set,metadata_del)
    
    def channels_get(self):
        return self._channels
    
    def channels_set(self,channels):
        self._channels.update(channels)
    
    def channels_del(self):
        self._channels = {}
        
    channels = property(channels_get,channels_set,channels_del)
        
    def modes_get(self):
        return self._modes
        
    def modes_set(self, modes):
        for give,mode,parameter in modes:
            if not give:
                if mode in self._modes:
                    del self._modes[mode]
            else:
                self._modes[mode] = parameter
        
    def modes_del(self):
        self._modes = {}
        
    modes = property(modes_get,modes_set,modes_del)


        
class Channel(Unique):
    
    def __init__(self,uid):
        Unique.__init__(self,uid) 
        
        self.topic = ''
        self.topic_time = 0
        self.topic_set_by = ''
        
        self.access = {}
        
        self._timestamp = tools.timestamp()
        
        self._users = {}
    
    def timestamp_get(self):
        return self._timestamp
    
    def timestamp_set(self,timestamp):
        self._timestamp = datetime.fromtimestamp(int(timestamp))
    
    def timestamp_del(self):
        self.timestamp = tools.timestamp()
        
    timestamp = property(timestamp_get,timestamp_set,timestamp_del)
    
    def users_get(self):
        return self._users
    
    def users_set(self,users):
        self._users.update(users)
    
    def users_del(self):
        self._users = {}
        
    users = property(users_get,users_set,users_del)
        
    def user_has_mode(self,user,mode):
        if user.uid in self._users:
            ur = self._users.get(user.uid)
            
            m = ur.get('modes',[])
            
            if mode in m:
                return True
                
        return False
        
    def modes_get(self):
        return self._modes
        
    def modes_set(self, modes):
    
        # Iterate over all given mode tuples
        for give,mode,parameter in modes:
            
            # If the paramater is a Unique(), record the mode
            # changes in a different manner (this is a directed
            # mode change).
            if isinstance(parameter,User):
            
                _user = self.users.get(parameter.uid)
                _cur_modes = _user.get('modes')
                if not _user:
                    continue
            
                if give and mode not in _cur_modes:
                    _user['modes'].append(mode)
                elif not give and mode in _cur_modes:
                    _user['modes'].remove(mode)
                    
            else:
                
                if not give:
                    if mode in self._modes:
                        del self._modes[mode]
                else:
                    self._modes[mode] = parameter
            
    def modes_del(self):
        self._modes = {}

    modes = property(modes_get,modes_set,modes_del)

    
    
    
