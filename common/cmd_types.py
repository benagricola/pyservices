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
        sr_fields['SERVER'] 	= ['name','password','hops','uid','description']
        sr_fields['OPERTYPE'] 	= ['type']
        sr_fields['UID'] 		= ['uid','timestamp','nick','hostname','displayed_hostname','ident','ip','signed_on','modes','parameters','gecos']
        sr_fields['METADATA'] 	= ['uid','name','value']
        sr_fields['FJOIN'] 		= ['channel','timestamp','modes','parameters','users']
        sr_fields['FHOST'] 		= ['hostname']
        sr_fields['FMODE'] 		= ['target','timestamp','modes','parameters']
        sr_fields['FTOPIC'] 	= ['channel','topic_time','topic_set_by','topic']
        sr_fields['TOPIC'] 		= ['channel','topic']
        sr_fields['PRIVMSG'] 	= ['uid','message']
        sr_fields['MODE'] 		= ['target','modes','parameters']
        sr_fields['PART'] 		= ['channel','reason']
        sr_fields['KICK'] 		= ['channel','user','reason']
        sr_fields['QUIT'] 		= ['reason']
        
        for name, value in sr_fields.items():
            setattr(self, name, value)

# This is where we set which keywords to enumerate
cmd = CMDTypes()

# This is where we set the field names and numbers we expect to find for a specified "SR" (Argument Parsing) type


def sr_reduce(args,required,ignore_reduce,ignore_gecos):
    if len(args) > required:
        if not ignore_reduce:
            raise ValueError('Given argument list contained more arguments than expected and you did not allow SR to reduce the arguments (set ignore_reduce = True on sr_assoc)')
            
        if ignore_gecos:
            _r = -1
        else:
            _r = 0
        # Always start at -1 when reducing because we dont want
        # to reduce any gecos / text into args. We subtract 1
        # plus the difference between the length of args we have
        # and the length we want (we always start by subtracting 
        # 1 because we always want to reduce at least 1 value.
        _l = _r - (1 + (len(args) - required))
        
        # Replace arguments _l:-1 with their values concatenated
        # by a space.
        args[_l:-1] = [' '.join(args[_l:-1])]


    elif len(args) < required:
        if not ignore_reduce:
            raise ValueError('Given argument list contained less arguments than expected and you did not allow SR to reduce the arguments (set ignore_reduce = True on sr_assoc)')
            
        
        _l = required - len(args)
        
        if ignore_gecos:
            gecos = args.pop()
            args.extend(itertools.repeat('',_l))
            args.append(gecos)
        else:
            args.extend(itertools.repeat('',_l))
    
    return args
    
    
def sr_assoc(cmdtype,args,ignore_reduce=False,ignore_gecos=True):
    _sr_fields = cmdtype
    

    args = sr_reduce(args,len(_sr_fields),ignore_reduce,ignore_gecos)
    

    if len(args) != len(_sr_fields):
            raise ValueError('Given arguments list did not match expected length')
    return dict(zip(_sr_fields,args))