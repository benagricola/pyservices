import logging

class CustomLogLevels(object):
	# Define custom log levels
	log_levels = {
		'CRITICAL': 50,
		'ERROR': 40,
		'WARNING': 30,
		'INFO': 20,
		'DEBUG': 15,
		'VERBOSE': 14,
		'DATABASE': 13,
		'NET': 11,
		'NOTSET': 0,
		50: 'CRITICAL',
		40: 'ERROR',
		30: 'WARNING',
		20: 'INFO',
		15: 'DEBUG',
		14: 'VERBOSE',
		13:	'DATABASE',
		11: 'NET',
		 0: 'NOTSET',
	}
	
	def __init__(self):
		# Insert our modified levels into logging module
		logging._levelNames = self.log_levels
		
	def __getattr__(self,name):
		return self.log_levels.get(name)
		
level = CustomLogLevels()