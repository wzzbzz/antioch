# antioch
# Copyright (c) 1999-2010 Phil Christensen
#
#
# See LICENSE for details

"""
Enable access to the messaging server
"""

import pkg_resources as pkg

from twisted.application import service
from twisted.python import log
from twisted.internet import defer, reactor
from twisted.internet.protocol import ClientCreator

import time

from txamqp import spec, protocol, content, client
from txamqp.client import TwistedDelegate

from txamqp.client import Closed as ClientClosed
from txamqp.queue import Closed as QueueClosed

from antioch import assets, json, parser

class MessageService(service.Service):
	"""
	Provides a service that holds a reference to the active
	AMQP connection.
	"""
	def __init__(self, queue_url, profile=False):
		"""
		Create a service with the given connection.
		"""
		self.url = parser.URL(queue_url)
		if(self.url['scheme'] != 'rabbitmq'):
			raise RuntimeError("Unsupported scheme %r" % self.url['scheme'])
		
		self.factory = ClientCreator(reactor, protocol.AMQClient,
			delegate = TwistedDelegate(),
			vhost	 = self.url['path'],
			spec	 = spec.loadString(
				pkg.resource_string('antioch.assets', 'amqp-specs/amqp0-8.xml'), 'amqp0-8.xml'
			),
		)
		self.profile = profile
		self.connection = None
		self.channel_counter = 0
	
	def get_queue(self, user_id):
		"""
		Get a queue object that stores up messages until committed.
		"""
		q = MessageQueue(self, user_id, self.profile)
		return q
	
	@defer.inlineCallbacks
	def setup_client_channel(self, user_id):
		"""
		Instantiate the client channel for a given user.
		"""
		chan = yield self.open_channel()
		
		exchange = 'user-exchange'
		queue = 'user-%s-queue' % user_id
		consumertag = "user-%s-consumer" % user_id
		routing_key = 'user-%s' % user_id
		
		yield chan.exchange_declare(exchange=exchange, type="direct", durable=True, auto_delete=True)
		yield chan.queue_declare(queue=queue, durable=True, exclusive=False, auto_delete=True)
		yield chan.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key)
		yield chan.basic_consume(queue=queue, consumer_tag=consumertag, no_ack=True)
		
		defer.returnValue(chan)
	
	@defer.inlineCallbacks
	def connect(self):
		"""
		Connect to the AMQP server.
		"""
		if(self.connection):
			defer.returnValue(self.connection)
		else:
			# print 'connecting %s' % self
			try:
				self.connection = yield self.factory.connectTCP(self.url['host'], int(self.url['port']))
				yield self.connection.authenticate(self.url['user'], self.url['passwd'])
			except Exception, e:
				raise EnvironmentError("Couldn't connect to RabbitMQ server on %s, exception: %s" % (self.url, e))
	
	@defer.inlineCallbacks
	def disconnect(self):
		"""
		Disconnect from the AMQP server.
		"""
		# print 'disconnecting %s' % self
		if(self.connection):
			chan0 = yield self.connection.channel(0)
			yield chan0.connection_close()
	
	@defer.inlineCallbacks
	def open_channel(self):
		"""
		Open a new channel to send messages.
		"""
		self.channel_counter += 1
		chan = yield self.connection.channel(self.channel_counter)
		yield chan.channel_open()
		defer.returnValue(chan)

class MessageQueue(object):
	"""
	Encapsulate and queue messages during a database transaction.
	"""
	def __init__(self, service, user_id, profile=False):
		"""
		Create a new queue for the provided service.
		"""
		self.profile = profile
		self.service = service
		self.user_id = user_id
		self.messages = []
	
	@defer.inlineCallbacks
	def start(self):
		self.chan = yield self.service.setup_client_channel(self.user_id)
		self.queue = yield self.service.connection.queue("user-%s-consumer" % self.user_id)
	
	@defer.inlineCallbacks
	def stop(self):
		try:
			yield self.chan.basic_cancel("user-%s-consumer" % self.user_id)
			yield self.chan.channel_close()
		except ClientClosed, e:
			pass
	
	def push(self, user_id, msg):
		"""
		Send a message to a certain user.
		"""
		self.messages.append((user_id, msg))
	
	@defer.inlineCallbacks
	def pop(self):
		try:
			msg = yield self.queue.get()
			data = json.loads(msg.content.body.decode('utf8'))
			defer.returnValue(data)
		except QueueClosed, e:
			defer.returnValue(None)
	
	@defer.inlineCallbacks
	def flush(self):
		"""
		Send all queued messages and close the channel.
		"""
		t = time.time()
		
		yield self.service.connect()
		
		if(self.profile):
			log.msg('connect took %s seconds' % (time.time() - t))
			t = time.time()
		
		exchange = 'user-exchange'
		chan = yield self.service.open_channel()
		if(self.profile):
			log.msg('channel open took %s seconds' % (time.time() - t))
			t = time.time()
		# yield chan.exchange_declare(exchange=exchange, type="direct", durable=False, auto_delete=True)
		while(self.messages):
			user_id, msg = self.messages.pop(0)
			routing_key = 'user-%s' % user_id
			data = json.dumps(msg)
			c = content.Content(data, properties={'content type':'application/json'})
			yield chan.basic_publish(exchange=exchange, content=c, routing_key=routing_key)
		
		try:
			yield chan.channel_close()
		except ClientClosed, e:
			pass
		
		if(self.profile):
			log.msg('purging queue took %s seconds' % (time.time() - t))
			t = time.time()
	
	