# antioch
# Copyright (c) 1999-2012 Phil Christensen
#
#
# See LICENSE for details

"""
Setup the application service.
"""

import os.path, logging

from antioch import conf
from antioch.core import messaging

import simplejson

from twisted.application import service
from twisted.internet import defer, task, reactor

log = logging.getLogger(__name__)

def get_command_support(command):
	"""
	Get the command class for the provided class name.
	"""
	from antioch import plugins
	for plugin in plugins.iterate():
		available_commands = plugin.get_commands()
		if(command in available_commands):
			klass = available_commands[command]
			child = getattr(plugin, 'transaction_child', None)
			return klass, child
	return None, None

class AppService(service.Service):
	"""
	A service that scans the appserver queue for messages to execute.
	"""
	def __init__(self):
		"""
		Create a new AppService.
		"""
		self.stopped = True
		self.consumer = None
		self.loop = task.LoopingCall(self.check_queue)
		self.loop.interval = 1
	
	def startService(self):
		"""
		Start the loop.
		"""
		log.info("started processing appserver queue")
		self.loop.start(self.loop.interval)
		reactor.addSystemEventTrigger("after", "startup", self._startService)
	
	@defer.inlineCallbacks
	def _startService(self):
		"""
		Start consuming messages asynchronously.
		"""
		self.consumer = yield messaging.get_async_consumer()
		self.stopped = False
		yield self.consumer.start_consuming()
	
	def stopService(self):
		"""
		Stop the loop.
		"""
		log.info("stopping appserver queue, please wait...")
		if not(self.stopped):
			self.stopped = True
			self.loop.stop()
			reactor.addSystemEventTrigger("before", "shutdown", self._stopService)
	
	@defer.inlineCallbacks
	def _stopService(self):
		"""
		Stop consuming messages.
		"""
		yield self.consumer.disconnect()
	
	@defer.inlineCallbacks
	def check_queue(self, *args, **kwargs):
		"""
		Check the queue for a message to execute.
		"""
		if(self.stopped):
			defer.returnValue(None)
		
		log.debug("checking for message for appserver: %s" % (self.consumer))
		msg = yield self.consumer.get_message()
		if(msg is None):
			log.info("appserver queue returned None, shutting down...")
			self.stopService()
			defer.returnValue(None)
		
		log.debug("got message from %s: %s" % (self.consumer, msg))
		
		klass, child = get_command_support(msg['command'])
		log.debug("Command support: %s with %s" % (klass, child))
		if(klass is None):
			log.error("no such command %s: %s" % (msg['command'], msg))
			yield self.consumer.send_message(header.reply_to, {
				'correlation_id': msg['correlation_id'],
				'error':'No such command: %s' % msg['command']
			})
			defer.returnValue(None)
		
		result = yield klass.run(transaction_child=child, **msg['kwargs'])
		
		log.debug("sending response to %s: %s" % (msg['reply_to'], result))
		yield self.consumer.send_message(msg['reply_to'], dict(correlation_id=msg['correlation_id'], **result))

