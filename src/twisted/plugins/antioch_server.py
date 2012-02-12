# antioch
# Copyright (c) 1999-2011 Phil Christensen
#
#
# See LICENSE for details

"""
twistd plugin support

This module adds a 'antioch' server type to the twistd service list.
"""

import warnings, logging

from zope.interface import classProvides

from twisted import plugin, __version__ as twisted_version
from twisted.python import usage, log
from twisted.internet import reactor
from twisted.application import internet, service

from ampoule import __version__ as ampoule_version

from antioch import conf, __version__
conf.init()

pylog = logging.getLogger('antioch')

messages = dict(
	startup = "appserver version %(antioch)s [ twisted v%(twisted)s, ampoule v%(ampoule)s ] now starting..." % dict(
		antioch = __version__,
		twisted = twisted_version,
		ampoule = ampoule_version,
	),
	shutdown = "shutting down appserver"
)

class antiochServer(object):
	"""
	The antioch application server startup class.
	"""
	
	classProvides(service.IServiceMaker, plugin.IPlugin)
	
	tapname = "antioch"
	description = "Run an antioch appserver."
	
	class options(usage.Options):
		"""
		Option-parsing for the antioch twistd plugin.
		"""
		optParameters =	[["port", "p", None, "antioch appserver port.", int],
						 ["web-port", "w", None, "antioch webserver port.", int],
						]
		optFlags =		[["no-client", "c", "Don't run the internal WSGI/Django-powered frontend client."],
						]
	
	@classmethod
	def makeService(cls, config):
		"""
		Setup the necessary network services for the application server.
		"""
		if(conf.get('suppress-deprecation-warnings')):
			warnings.filterwarnings('ignore', r'.*', DeprecationWarning)
		if(conf.get('suppress-user-warnings')):
			warnings.filterwarnings('ignore', r'.*', UserWarning)
		
		class PythonLoggingMultiService(service.MultiService):
			def setServiceParent(self, parent):
				service.MultiService.setServiceParent(self, parent)
				observer = log.PythonLoggingObserver(loggerName='antioch.appserver')
				def appserver_log_level(event):
					if not(event['isError']):
						event['logLevel'] = logging.DEBUG
					observer.emit(event)
				parent.setComponent(log.ILogObserver, appserver_log_level)
		
		master_service = PythonLoggingMultiService()
		
		from antioch import messaging
		messaging.installServices(master_service, conf.get('queue-url'), conf.get('profile-queue'))
		msg_service = master_service.getServiceNamed('message-service')	
		
		from antioch.core import tasks
		task_service = tasks.TaskService()
		task_service.setName("task-daemon")
		task_service.setServiceParent(master_service)
		
		from antioch.core import appserver
		app_service = appserver.AppService(msg_service)
		app_service.setName("app-service")
		app_service.setServiceParent(master_service)
		
		if not(config['no-client']):
			from antioch import client
			web_service = client.DjangoServer(msg_service, port=config['port'])
			web_service.setName("django-server")
			web_service.setServiceParent(master_service)
		
		reactor.addSystemEventTrigger("before", "startup", lambda: pylog.info(messages['startup']))
		reactor.addSystemEventTrigger("before", "shutdown", lambda: pylog.info(messages['shutdown']))
		
		return master_service
