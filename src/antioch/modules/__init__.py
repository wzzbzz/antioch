# antioch
# Copyright (c) 1999-2011 Phil Christensen
#
#
# See LICENSE for details

"""
Modules add additional client or server functionality
"""

import os, sys

from zope import interface

from twisted import plugin

def autodiscover():
	"""
	Auto-discover INSTALLED_APPS plugin.py modules and fail silently when
	not present.
	"""
	from django.conf import settings
	from django.utils.importlib import import_module
	from django.utils.module_loading import module_has_submodule
	
	for app in settings.INSTALLED_APPS:
		mod = import_module(app)
		# Attempt to import the app's plugin module.
		try:
			plugin_mod = import_module('%s.plugin' % app)
			for mod_name in dir(plugin_mod):
				if(mod_name.startswith('_')):
					continue
				mod = getattr(plugin_mod, mod_name)
				if(IModule.providedBy(mod)):
					yield mod
		except:
			# Decide whether to bubble up this error. If the app just
			# doesn't have a plugin module, we can ignore the error
			# attempting to import it, otherwise we want it to bubble up.
			if module_has_submodule(mod, 'plugin'):
				raise

def iterate():
	for module in autodiscover():
		yield module()

def get(name):
	for plugin_mod in autodiscover():
		if(module.name == name):
			m = module()
			return m
	return None

def discover_commands(mod):
	from antioch.core import transact
	t = mod.__dict__.items()
	return dict(
		[(k,v) for k,v in t if isinstance(v, type) and issubclass(v, transact.WorldTransaction)]
	)

class IModule(interface.Interface):
	name = interface.Attribute('Name of this module.')
	script_url = interface.Attribute('Plugin script URL.')
	
	def get_environment(self):
		"""
		Return a dict of items to add to the verb environment.
		"""
	
	def get_resource(self, user):
		"""
		Return the instantiated resource for this plugin.
		"""
	
	def handle_message(self, msg):
		"""
		Handle a message generated by the verb environment.
		"""
	
	def get_commands(self):
		"""
		Return a dict of WorldTransaction/amp.Command classes provided by this module.
		"""
	
	def activate_client_commands(self, client):
		"""
		Given the athena.LiveElement instance, install the available command support.
		"""