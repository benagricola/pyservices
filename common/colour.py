import logging

import tools

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = xrange(30,38)

#The background is set with 40 plus the number of the color, and the foreground with 30

#These are the sequences need to get colored ouput
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"

def formatter_message(message):
    return message.replace("$RESET", RESET_SEQ).replace("$BOLD", BOLD_SEQ)


COLORS = {
    'WARNING': YELLOW,
    'INFO': WHITE,
    'NET': MAGENTA,
    'VERBOSE': BLUE,
    'DEBUG': BLUE,
    'DATABASE': BLUE,
    'CRITICAL': YELLOW,
    'ERROR': RED,
}

def format_colour(colour,string):
        return COLOR_SEQ % (colour) + string + RESET_SEQ
        
        
class ColoredFormatter(logging.Formatter):
    def __init__(self, msg, max_width = 120, line_offset = 48):
        logging.Formatter.__init__(self, msg)
        self.max_width = max_width
        self.line_offset = line_offset
        


    

        
    def format(self, record):
    
        msg = tools.word_wrap(str(record.msg),self.max_width,self.line_offset)
        
        if msg.startswith('<<'):
            record.msg = COLOR_SEQ % RED + '<<' + RESET_SEQ + msg[2:] 
        elif msg.startswith('>>'):
            record.msg = COLOR_SEQ % GREEN + '>>' + RESET_SEQ + msg[2:] 
        elif not msg.startswith('--'):
            record.msg = COLOR_SEQ % CYAN + '-- ' + RESET_SEQ + msg
            
        levelname = record.levelname
        
        
        if levelname in COLORS:
            levelname_color = COLOR_SEQ % COLORS[levelname] + levelname + RESET_SEQ
            record.levelname = levelname_color
        
        return logging.Formatter.format(self, record)
