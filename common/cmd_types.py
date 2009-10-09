"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 PyServices Development Team	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import itertools

"""
    'Enumerates' a set of items for use as constants
    elsewhere in the application.
"""
class CMDTypes(object):
    def __init__(self):
        sr_fields = {}
        sr_fields['SERVER']     = ['name','password','hops','uid','description']
        sr_fields['OPERTYPE']   = ['type']
        sr_fields['UID']        = ['uid','timestamp','nick','hostname','displayed_hostname','ident','ip','signed_on','modes','parameters','gecos']
        sr_fields['METADATA']   = ['uid','name','value']
        sr_fields['FJOIN']      = ['channel','timestamp','modes','parameters','users']
        sr_fields['FHOST']      = ['hostname']
        sr_fields['FMODE']      = ['target','timestamp','modes','parameters']
        sr_fields['FTOPIC']     = ['channel','topic_time','topic_set_by','topic']
        sr_fields['TOPIC']      = ['channel','topic']
        sr_fields['PRIVMSG']    = ['uid','message']
        sr_fields['MODE']       = ['target','modes','parameters']
        sr_fields['PART']       = ['channel','reason']
        sr_fields['KICK']       = ['channel','user','reason']
        sr_fields['QUIT']       = ['reason']
        
        self.__dict__ = sr_fields
        
cmd = CMDTypes()


def sr_reduce(args,required,ignore_reduce,reduce_gecos):
    if len(args) > required:
        if not ignore_reduce:
            raise ValueError('Given argument list contained more arguments than expected and you did not allow SR to reduce the arguments (set ignore_reduce = True on sr_assoc)')
            
        if reduce_gecos:
            _l = -1 - (len(args) - required)
            _r = None
        else:
            _l = 0 - (len(args) - required)
            _r = -1

        args[_l:_r] = [' '.join(args[_l:_r])]

    elif len(args) < required:
        if not ignore_reduce:
            raise ValueError('Given argument list contained less arguments than expected and you did not allow SR to reduce the arguments (set ignore_reduce = True on sr_assoc)')
            
        
        _l = required - len(args)
        
        if not reduce_gecos:
            gecos = args.pop()
            args.extend(itertools.repeat('',_l))
            args.append(gecos)
        else:
            args.extend(itertools.repeat('',_l))
    
        
    return args
    
    
def sr_assoc(cmdtype,args,ignore_reduce=False,reduce_gecos=True):
    _sr_fields = cmdtype
    

    args = sr_reduce(args,len(_sr_fields),ignore_reduce,reduce_gecos)
    

    if len(args) != len(_sr_fields):
            raise ValueError('Given arguments list did not match expected length')
    return dict(zip(_sr_fields,args))