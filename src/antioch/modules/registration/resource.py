# antioch
# Copyright (c) 1999-2010 Phil Christensen
#
#
# See LICENSE for details

import os.path

import pkg_resources as pkg

from nevow import loaders, rend

class AccountConfirmationPage(rend.Page):
	def locateChild(self, ctx, segments):
		print segments
		if(len(segments) != 2):
			return super(rend.Page, self).locateChild(ctx, segments)

