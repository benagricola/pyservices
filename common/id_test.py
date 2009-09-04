#!/usr/bin/env python
import tools 

for r in xrange(500000):
	i = tools.UIDGenerator.generate()
	print i