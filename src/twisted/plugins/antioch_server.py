# antioch
# Copyright (c) 1999-2011 Phil Christensen
#
#
# See LICENSE for details

"""
twistd plugin support

This module adds a 'antioch' server type to the twistd service list.
"""

import warnings

from zope.interface import classProvides

from twisted import plugin
from twisted.python import usage, log
from twisted.internet import reactor
from twisted.application import internet, service

from antioch import conf
conf.init()

class antiochServer(object):
	"""
	The antioch application server startup class.
	"""
	
	classProvides(service.IServiceMaker, plugin.IPlugin)
	
	tapname = "antioch"
	description = "Run a set of antioch servers."
	
	class options(usage.Options):
		"""
		No option-parsing for the antioch twistd plugin.
		"""
	
	@classmethod
	def makeService(cls, config):
		"""
		Setup the necessary network services for the application server.
		"""
		if(conf.get('suppress-deprecation-warnings')):
			warnings.filterwarnings('ignore', r'.*', DeprecationWarning)
		
		from antioch.util import logging
		error_log = conf.get('error-log')
		if(error_log):
			log.startLogging(open(error_log, 'w'))
			reactor.addSystemEventTrigger('after', 'startup', logging.customizeLogs)
		else:
			def _customizeLogs():
				logging.customizeLogs(colorize=True)
			reactor.addSystemEventTrigger('after', 'startup', _customizeLogs)
		
		master_service = service.MultiService()
		
		from antioch import messaging
		messaging.installServices(master_service, conf.get('queue-url'), conf.get('profile-queue'))
		msg_service = master_service.getServiceNamed('message-service')	
		
		from antioch.core import tasks
		task_service = tasks.TaskService()
		task_service.setName("task-daemon")
		task_service.setServiceParent(master_service)
		
		from antioch.core import appserver
		app_service = appserver.AppServer(msg_service)
		app_service.setName("app-server")
		app_service.setServiceParent(master_service)
		
		from antioch import client
		web_service = client.DjangoServer(msg_service)
		web_service.setName("django-server")
		web_service.setServiceParent(master_service)
		
		task_service.run()
		
		return master_service
