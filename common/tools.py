"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 PyServices Development Team	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import hashlib, string, random, sys, os, re, imp, inspect, time, math

"""
    Generates a valid HMAC challenge string using 
    random.sample on a list of allowed characters.
    Removes = from the list of allowed since it is
    used to distinguish key from value in the CAPAB
    output.
"""
def hmac_challenge_string(length=19):
    _chars = list(string.ascii_letters + string.digits + string.punctuation)
    _chars.remove('=')
    return ''.join(random.sample(_chars,length))


"""
    Generates HMAC string from given challenge and password, 
    prepending it with the HMAC identifier utilized by the IRCd
"""
def hmac(password,challenge):   
        def xor(char,byte): 
            return chr(ord(char) ^ byte)
            
        _lp,_rp = ((''.join(xor(c,x) for c in password.encode('ascii'))) for x in (0x5c,0x36))
    
        _rs = hashlib.sha256(_rp + challenge).hexdigest()
        _hs = hashlib.sha256(_lp + _rs).hexdigest()
        return 'HMAC-SHA256:%s' % _hs
        

"""
    Generates a unique UID using baseconvert
"""
class UIDGenerator:
    
    """
    Converts a base 10 integer into a base len(uppercase + digits) 
    string, then pads it to n characters if required.
    """
    @classmethod
    def baseconvert(cls,n,pad=6):
        

        digits = string.ascii_uppercase + string.digits
        base = len(digits)
        
        try:
            n = int(n)
            base = int(base)
        except:
            return ""

        if n < 0 or base < 2 or base > 36:
            return ""

        s = ""
        while 1:
            r = n % base
            s = digits[r] + s
            n = n / base
            if n == 0:
                break
        if len(s) < pad:
            return 'A'* (pad-len(s)) + s
        else:
            return s
    
    
    @classmethod
    def generate(cls,list_in_use):
        _chars = list(string.ascii_uppercase + string.digits)
        
        if not hasattr(cls,'uid'):
                cls.uid = 0
        
        
        v = cls.baseconvert(cls.uid)
        cls.uid += 1
        while v in list_in_use.keys():
            v = cls.baseconvert(cls.uid)
            cls.uid += 1
            
        return v
        
"""
    Given a list of tuples (give,mode,value) from
    the spanningtree separate_modes function, this
    function returns a mode => (give,value) dictionary 
    for each mode that is applied to a channel.
"""   
def applied_modes(modes):
    r = {}
    for give,mode,value in modes:
            r[mode] = (give,value)
    
    return r
    
"""
    Utility function to check if a
    string contains any characters
    in the given set.
"""
def contains_any(str, set):
    for c in set:
        if c in str: return True;
    return False;


"""
    Wraps a string to a specified length if it is
    longer than <width> characters, offsetting following
    lines to a certain length. Shortens the first line
    by offset so that all lines are of the same width.
"""
def word_wrap(string, width=80, offset=0):
    splitpos = []
    spr = '\n' + offset * " "
    left_marker = 0
    right_marker = (width - offset) - 1
    
    while len(string) > right_marker:	
        last_space = string.rfind(' ',left_marker,right_marker)
        
        if last_space < 0 or last_space == left_marker:
            splitpos.append((left_marker,right_marker))
            
            left_marker = right_marker
            right_marker = (right_marker + width + 1) - offset
            
        else:
            splitpos.append((left_marker,last_space))
            
            left_marker = last_space
            right_marker = (last_space + width + 1) - offset
        
        if right_marker > len(string):
            splitpos.append((left_marker,len(string)))
            
    else:
        if len(string) < width:
            return string
        else:
            return spr.join((string[left:right].strip() for left, right in splitpos))	
        
        
        
def pad(string,length = 30,left = False):

    if len(string) < length:
        m = length - len(string)
    
        if left:
            return (m * " ") + string
        else:
            return string + (m * " ")
        
    else:
        return string

"""
Returns a string containing the name 
of the function depth n which called the
current function.
"""
def called_by(depth=1):
    depth += 1
    return sys._getframe(depth).f_code.co_name

    
"""
    Returns all classes in all modules in
    a package as a name, class tuple.
    
    Pretty ugly hack but only way I've found
    so far to auto-import extensions.
"""
def find_classes(package):
    files = [re.sub('\.py$', '', f) for f in os.listdir(package) if f[-3:].endswith('.py') and '__init__' not in f]

    return [inspect.getmembers(__import__(package + '.' + modname,None,None,'*'),inspect.isclass)[0] for modname in files]
    
 

def get_docstring(obj,prefix='',cmdname=''):
    mts = [method for name, method in inspect.getmembers(obj,inspect.ismethod) if name == (prefix + cmdname).lower()]

    if len(mts) > 1:
        return True
    elif len(mts) > 0:
        meth = mts[0]
        return inspect.getdoc(meth)
    else:
        return False

"""
    Generates a timestamp for operations that require it
"""
def timestamp():  
    return int(math.floor(time.time()))

""" 
    Splits a list into equal length lists with size n
"""
def chunks(l, n):  
    for i in xrange(0, len(l), n):
            yield l[i:i+n]
   
"""
    Returns all functions in a given class,
    possibly matching a prefix.
"""
def find_names(cls,regex=r'.*'):
    return [name for name, method in inspect.getmembers(cls,inspect.ismethod) if re.match(regex,name) is not None]

def find_methods(cls,regex=r'.*'):
    return [method for name, method in inspect.getmembers(cls,inspect.ismethod) if re.match(regex,name) is not None]
    
