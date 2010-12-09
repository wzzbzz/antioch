# antioch
# Copyright (c) 1999-2010 Phil Christensen
#
#
# See LICENSE for details

"""
Bootstrap support code.
"""

from __future__ import with_statement

import traceback, subprocess

from antioch import exchange, dbapi

def get_dsn(db_url):
	match = dbapi.URL_RE.match(db_url)
	if not(match):
		raise ValueError("Invalid db URL: %s" % db_url)
	dsn = match.groupdict()
	dsn['db'] = dsn['db'][1:]
	return dsn

def initialize_database(psql_path, db_url, psql_args=[], quiet=True):
	dsn = get_dsn(db_url)
	
	kwargs = {}
	if(quiet):
		kwargs['stderr'] = subprocess.STDOUT
	
	subprocess.Popen([psql_path,
		'-h', dsn.get('host') or 'localhost',
		'-p', dsn.get('port') or '5432',
		'-U', 'postgres',
		'-c', "CREATE USER %(user)s WITH UNENCRYPTED PASSWORD '%(passwd)s';" % dsn,
	] + list(psql_args), stdout=subprocess.PIPE, **kwargs).wait()
	
	subprocess.Popen([psql_path,
		'-h', dsn.get('host') or 'localhost',
		'-p', dsn.get('port') or '5432',
		'-U', 'postgres',
		'-c', 'DROP DATABASE %(db)s;' % dsn,
	] + list(psql_args), stdout=subprocess.PIPE, **kwargs).wait()
	
	subprocess.Popen([psql_path,
		'-h', dsn.get('host') or 'localhost',
		'-p', dsn.get('port') or '5432',
		'-U', 'postgres',
		'-c', 'CREATE DATABASE %(db)s WITH OWNER %(user)s;' % dsn,
	] + list(psql_args), stdout=subprocess.PIPE, **kwargs).wait()

def load_schema(psql_path, db_url, schema_path, create=False):
	dsn = get_dsn(db_url)
	
	cmd = [psql_path,
		'-f', schema_path,
		'-h', dsn['host'],
		'-p', dsn.get('port') or '5432',
		'-U', dsn['user'],
		dsn['db'],
	]
	
	child = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	child.wait()

def load_python(pool, python_path):
	with exchange.ObjectExchange(pool) as x:
		execfile(python_path, globals(), dict(exchange=x))
