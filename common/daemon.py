"""

        +-------------------------------------+
        |   PyServices IRCd Services Daemon   |
        +-------------------------------------+

    PyServices: (C) 2009 Ben Agricola	
    
    This program is free but copyrighted software; see
    the file COPYING for details.
    
"""

import logging, optparse, os, sys, signal, pwd, grp, time, errno

"""
    Implements a base class allowing daemonization
    of an application.
"""
class Daemon(object):
    
    default_config = '' # OVERRIDE THIS
    root_dir = '/' 
    
    gid = None
    uid = None
    
    daemonize = True
    
    name = ''
    
    def __init__(self,name):
        self.name = name
        
    def main(self):
        signal.signal(signal.SIGHUP, self.reload_handler)

        self.parse_options()
        action = self.options.action
        
        self.parse_config()
        
        self.uid = self.get_uid_from_conf(self.uid)
        self.gid = self.get_gid_from_conf(self.gid)
        
        if action == 'start':
            self.start()
        elif action == 'stop':
            self.stop()
        elif action == 'restart':
            self.stop(True)
            self.start()
        elif action == 'rehash':
            self.rehash()
        else:
            raise ValueError(action)

    
    def reload_handler(self,signum,frame):
        self.parse_config()
        
        
    def parse_config(self):
        """ 
            Override this with the applications' favoured way
            of parsing its config. This method MUST make sure
            that Daemon.pid_file is set.
        """
        
        # self.pid_file = cp.get(self.section, 'pidfile')
        # self.log_file = cp.get(self.section, 'logfile')
        # self.log_level = cp.get(self.section, 'loglevel')
        # Can also set self.gid and self.uid

        
    def start_logging(self):
        """Override this to setup logging"""
        
        # Can use self.log_file, self.log_level etc    
        
        
    def parse_options(self):
        p = optparse.OptionParser('Typical Usage: %s start|stop|restart|rehash [options]' % (self.name))
        
        p.add_option('--start', dest='action',action='store_const', const='start', default='start',help='Start the daemon (the default action)')
        p.add_option('--rehash', dest='action',action='store_const', const='rehash', default='start',help='Rehash the daemon')
        p.add_option('--stop', dest='action',action='store_const', const='stop', default='start',help='Stop the daemon')
        p.add_option('-c', dest='config_filename',action='store', default=self.default_config,help='Specify alternate configuration file name')
        p.add_option('-n', '--nodaemon', dest='daemonize',action='store_false', default=True,help='Run in the foreground')
        
        self.options, self.args = p.parse_args()
        
        try:
            if self.args[0].lower() in ('start','stop','restart','rehash'):
                self.options.action = self.args[0].lower()
        
        except: 
            pass

        if not os.path.exists(self.options.config_filename):
            p.error('Configuration file not found: %s' % self.options.config_filename)
        else:
            self.config_filename = self.options.config_filename
            
            
    def on_sigterm(self, signalnum, frame):
        """Handle segterm by treating as a keyboard interrupt"""
        
        raise KeyboardInterrupt('SIGTERM')

    def add_signal_handlers(self):
        """Register the sigterm handler"""
        
        signal.signal(signal.SIGTERM, self.on_sigterm)

        
    def setup_run_user(self):
        """Override to perform setup tasks with initial user privs"""
    
    def setup_run_restricted(self):
        """Override to perform setup tasks with restricted user privs"""
    
    
    """
        Ensure the log and pid file directories exist and are writable
    """
    def prepare_dirs(self):
        
        for fn in (self.pid_file, self.log_file):
        
            if not fn:
                continue
                
            parent = os.path.dirname(fn)
            
            if not os.path.exists(parent):
                os.makedirs(parent)
                self.chown(parent)
    

    """
        Drop into restricted privileges if required
    """
    def set_uid(self):
    
        if self.gid:
            try:
                os.setgid(self.gid)
            except OSError, (code, message):
                sys.exit("Cannot setgid(%d): %s, %s" % (self.gid, code, message))
                
        if self.uid:
            try:
                os.setuid(self.uid)
            except OSError, (code, message):
                sys.exit("Cannot setuid(%d): %s, %s" % (self.uid, code, message))

                
    """
        Change the ownership of a specific file 
        to match the daemon uid/gid
    """
    def chown(self, fn):
        
        if self.uid or self.gid:
        
            uid = self.uid
            
            if not uid:
                uid = os.stat(fn).st_uid
                
            gid = self.gid

            if not gid:
                gid = os.stat(fn).st_gid
                
            try:
                os.chown(fn, uid, gid)
            except OSError, (code, message):
                sys.exit("Cannot chown(%s, %d, %d): %s, %s" % (repr(fn), uid, gid, code, message))

     
        
    """
        Check the pid file.

        Stop using sys.exit() if another instance is already running.
        If the pid file exists but no other instance is running,
        delete the pid file.
    """
    def check_pid(self):
       
        if not self.pid_file:
            return

        if os.path.exists(self.pid_file):
            try:
                pid = int(open(self.pid_file).read().strip())
            except ValueError:
                msg = 'PID file %s contains a non-integer value' % self.pid_file
                sys.exit(msg)
            try:
                os.kill(pid, 0)
            except OSError, (code, text):
                if code == errno.ESRCH:
                    # The pid doesn't exist, so remove the stale pidfile.
                    os.remove(self.pid_file)
                else:
                    msg = ("Failed to check status of process %s from PID file %s: %s" % (pid, self.pid_file, text))
                    sys.exit(msg)
            else:
                msg = ('Instance already running (pid %s), exiting' % pid)
                sys.exit(msg)

                
    """
        Verify the user has access to write to the pid file.
    """
    def check_pid_writable(self):
        
        if not self.pid_file:
            return
        if os.path.exists(self.pid_file):
            check = self.pid_file
        else:
            check = os.path.dirname(self.pid_file)
        if not os.access(check, os.W_OK):
            msg = 'Unable to write to PID file %s' % self.pid_file
            sys.exit(msg)

            
    """
        Write to the pid file
    """
    def write_pid(self):
        
        if self.pid_file:
            open(self.pid_file, 'wb').write(str(os.getpid()))

            
    """
        Delete the pid file
    """
    def remove_pid(self):
        
        if self.pid_file and os.path.exists(self.pid_file):
            os.remove(self.pid_file)


    def get_uid_from_conf(self,cfg_value):
        if cfg_value:
            try:
                return int(cfg_value)    
            except ValueError:
            
                try:
                    return pwd.getpwnam(cfg_value)[2]
                except KeyError:
                    raise ValueError("User %s could not be converted to a valid UID" % cfg_value)

                
    def get_gid_from_conf(self,cfg_value):
        if cfg_value:
            try:
                return int(cfg_value)    
            except ValueError:
            
                try:
                    return grp.getgrnam(cfg_value)[2]
                except KeyError:
                    raise ValueError("Group %s could not be converted to a valid GID" % cfg_value)   
                    
    """
        Detach a process from the terminal 
        and continue as a daemon.
    """
    def daemonize(self):
        
        if os.fork():   # launch child and...
            os._exit(0) # kill off parent
            
        os.setsid()
        
        if os.fork():   # launch child and...
            os._exit(0) # kill off parent again.
            
        os.umask(077)
        
        null=os.open('/dev/null', os.O_RDWR)
        
        for i in range(3):
            try:
                os.dup2(null, i)
            except OSError, e:
                if e.errno != errno.EBADF:
                    raise
                    
        os.close(null)

    
   
    """ 
        Switches into the correct working directory for an app
    """
    def switch_cwd(self):
        if self.root_dir:
           os.chdir(self.root_dir) 
    

    """ 
        Force config reload of remote process
    """
    def rehash(self):
        if os.path.exists(self.pid_file):
            try:
                pid = int(open(self.pid_file).read().strip())
            except ValueError:
                msg = 'PID file %s contains a non-integer value' % self.pid_file
                sys.exit(msg)
            try:
                os.kill(pid, signal.SIGHUP)
                print "Rehashing..."
            except OSError, (code, text):
                if code == errno.ESRCH:
                    # The pid doesn't exist, so remove the stale pidfile.
                    os.remove(self.pid_file)
            
    """
        Initialize and run the daemon
    """
    def start(self):
    
        print "Daemon starting..."
        
        # Switch into correct cwd
        self.switch_cwd()
        
        # Avoid running if PID is already in use
        self.check_pid()
        
        self.add_signal_handlers()
      
        self.prepare_dirs()

        self.start_logging()
        
        try:
            # Execute any setup tasks required before setuid/gid
            self.setup_run_user()

            # Set the UID / GID
            self.set_uid()
            
            # Make sure current UID / GID can write to the PID file
            self.check_pid_writable()
            
            # Execute any setup tasks on the restricted UID / GID
            self.setup_run_restricted()

            # Attempt to fork the process if required
            if self.daemonize:
                self.daemonize()
                logging.getLogger('DAEMON').info("Daemonized successfully")
                
        except:
            logging.getLogger('DAEMON').error('Exception encountered during daemonization process')
            raise

        # Write the PID file 
        self.write_pid()
        
        print "Daemon running (PID %s)" % (str(os.getpid()))
        
        try:

            try:
                self.run()
            except (KeyboardInterrupt, SystemExit):
                pass
            except:
                logging.getLogger('DAEMON').error('Uncaught error encountered during execution.')
                raise
        finally:
            self.remove_pid()
            logging.getLogger('DAEMON').info('Daemon process exited.')
           

    """
        Stop the running process
    """       
    def stop(self,restart=False):
        
        if self.pid_file and os.path.exists(self.pid_file):
        
            pid = int(open(self.pid_file).read())
            os.kill(pid, signal.SIGTERM)
            
            # Wait for the process to die
            for n in range(10):
                time.sleep(0.25)
                try:
                    os.kill(pid, 0)
                except OSError, why:
                    if why[0] == errno.ESRCH:
                        # Process has died, exit
                        print "Daemon exited."
                        break
                    else:
                        raise
            else:
                sys.exit("Daemon PID %d did not die." % pid)
                
        elif not restart:
            sys.exit("Daemon not running.")
        else:
            print "Daemon not running."
    
