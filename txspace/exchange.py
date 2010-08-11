"""
the txspace ObjectExchange

essentially a replacement for the old Registry class, combined with
some new requirements needed by the DB persistence layer.

this is the connecting thread between the database and verb code
during a transaction. it is responsible for loading and saving objects,
verbs, properties and permissions, as well as caching objects loaded
during a single verb transaction.


permissions and properties/verbs

the only time an object's permissions are consulted is when we are adding
a verb or property. once it is added, any interactions with the verb or property
should examine those objects themselves. during deletion, both the object and the
attribute should be checked, for the following reason:


the owner of a property/verb should be able to delete something they own from
an object they don't (the only way that attribute could have been added in the
first place was because the object was writable to them).

however, the owner of the object should also have the ability to delete that
attribute. if so, then do they have rights to do other things (change properties,
edit verbs) simply because the attributes were defined on something they owned?

No, they don't. They can remove things they don't own from their object, but they cannot
change the value of those items.

"""
import crypt

from twisted.internet import defer
from twisted.python import util

from txspace import sql, model, errors

class ObjectExchange(object):
	def __init__(self, pool, ctx=None):
		self.cache = util.OrderedDict()
		self.pool = pool
		
		if(isinstance(ctx, int)):
			self.ctx = self.get_object(ctx)
		else:
			self.ctx = ctx
	
	def get_context(self):
		return self.ctx
	
	def instantiate(self, obj_type, record=None, *additions, **fields):
		records = []
		if(record):
			records.append(record)
		if(additions):
			records.extend(additions)
		if(fields):
			records.append(fields)
		
		results = []
		for record in records:
			object_id = record.get('id', None)
			object_key = '%s-%s' % (obj_type, object_id)
			if(object_key in self.cache):
				obj = self.cache[object_key]
			else:
				# no ID passed, we're creating a new object
				if(object_id is None):
					def fail(record):
						raise RuntimeError("Don't know how to make an object of type '%s'" % obj_type)
					
					maker = getattr(self, '_mk%s' % obj_type, fail)
					obj = maker(record)
					self.save(obj)
				else:
					obj = self.load(obj_type, object_id)
			
			results.append(obj)
		
		if(len(records) == 1):
			return results[0]
		
		return results
	
	new = lambda s, *a, **kw: s.instantiate('object', *a, **kw)
	
	def _mkobject(self, record):
		obj = model.Object(self)
		
		obj._name = record.get('name', '')
		obj._unique_name = record.get('unique_name', False)
		obj._owner_id = record.get('owner_id', None)
		obj._location_id = record.get('location_id', None)
		
		return obj
	
	def _mkverb(self, record):
		origin = self.instantiate('object', id=record['origin_id'])
		verb = model.Verb(origin)
		
		verb._code = record.get('code', '')
		verb._owner_id = record.get('owner_id', None)
		verb._ability = record.get('ability', False)
		verb._method = record.get('method', False)
		verb._origin_id = record['origin_id']
		
		return verb
	
	def _mkproperty(self, record):
		origin = self.instantiate('object', id=record['origin_id'])
		prop = model.Property(origin)
		
		prop._name = record['name']
		prop._origin_id = record['origin_id']
		prop._value = record.get('value', '')
		prop._dynamic = record.get('dynamic', False)
		prop._owner_id = record.get('owner_id', None)
		
		return prop
	
	def _mkpermission(self, record):
		origin = None
		for origin_type in ('object', 'verb', 'property'):
			origin_id = record.get('%s_id' % origin_type, None)
			if(origin_id):
				origin = self.instantiate(origin_type, id=origin_id)
				break
		
		assert origin is not None, "Can't determine an origin for permission record: %s" % record
		
		perm = model.Permission(origin)
		
		perm.object_id = record.get('object_id', None)
		perm.verb_id = record.get('verb_id', None)
		perm.property_id = record.get('property_id', None)
		    
		perm.rule = record.get('rule', 'allow')
		perm.permission_id = record.get('permission_id', None)
		perm.type = record.get('type', 'group')
		perm.subject_id = record.get('subject_id', None)
		perm.group = record.get('group', 'everyone')
		
		return perm
	
	def commit(self):
		for id, obj in self.cache.items():
			self.save(obj)
			del self.cache[id]
	
	def load(self, obj_type, obj_id):
		obj_key = '%s-%s' % (obj_type, obj_id)
		if(obj_key in self.cache):
			return self.cache[obj_key]
		
		items = self.pool.runQuery(sql.build_select(obj_type, id=obj_id))
		if not(items):
			raise errors.NoSuchObjectError("%s #%s" % (obj_type, obj_id))
		
		def fail(record):
			raise RuntimeError("Don't know how to make an object of type '%s'" % obj_type)
		
		maker = getattr(self, '_mk%s' % obj_type, fail)
		obj = maker(items[0])
		obj.set_id(obj_id)
		self.cache[obj_key] = obj
		
		return obj
	
	def save(self, obj):
		obj_type = type(obj).__name__.lower()
		obj_id = obj.get_id()
		
		if(obj_type == 'object'):
			attribs = dict(
				name		= obj._name,
				unique_name	= ('f', 't')[obj._unique_name],
				owner_id	= obj._owner_id,
				location_id	= obj._location_id,
			)
		elif(obj_type == 'verb'):
			attribs = dict(
				code		= obj._code,
				owner_id	= obj._owner_id,
				origin_id	= obj._origin_id,
				ability		= ('f', 't')[obj._ability],
				method		= ('f', 't')[obj._method],
			)
		elif(obj_type == 'property'):
			attribs = dict(
				name		= obj._name,
				value		= obj._value,
				owner_id	= obj._owner_id,
				origin_id	= obj._origin_id,
				dynamic		= ('f', 't')[obj._dynamic],
			)
		elif(obj_type == 'permission'):
			pass
		else:
			raise RuntimeError("Don't know how to save an object of type '%s'" % obj_type)
		
		if(obj_id):
			self.pool.runOperation(sql.build_update(obj_type, attribs, dict(id=obj_id)))
		else:
			attribs['id'] = sql.RAW('DEFAULT')
			result = self.pool.runQuery(sql.build_insert(obj_type, attribs) + ' RETURNING id')
			obj.set_id(result[0]['id'])
		
		object_key = '%s-%s' % (obj_type, obj.get_id())
		if(object_key not in self.cache):
			self.cache[object_key] = obj
	
	def get_object(self, key, return_list=False):
		try:
			key = int(key)
		except:
			pass
		
		items = None
		if(isinstance(key, basestring)):
			if(key.startswith('#')):
				end = key.find("(")
				if(end == -1):
					end = key.find( " ")
				if(end == -1):
					end = len(key)
				key = int(key[1:end])
			else:
				items = self.pool.runQuery(sql.build_select('object', name=sql.RAW(sql.interp('LOWER(%%s) = LOWER(%s)', key))))
				if(len(items) == 0):
					raise errors.NoSuchObjectError(key)
				elif(len(items) > 1):
					if(return_list):
						return self.instantiate('object', *items)
					else:
						raise errors.AmbiguousObjectError(key, items)
				else:
					return self.instantiate('object', items[0])
		
		if(isinstance(key, int)):
			if(key == -1):
				return None
			
			return self.load('object', key)
		else:
			raise ValueError("Invalid key type: %r" % repr(key))
	
	def get_parents(self, object_id, recurse=False):
		#NOTE: the heavier a parent weight is, the more influence its inheritance has.
		# e.g., if considering inheritance by left-to-right, the leftmost ancestors will
		#       have the heaviest weights.
		parent_ids = ancestor_ids = self.pool.runQuery(sql.interp(
			"""SELECT parent_id AS id
				FROM object_relation
				WHERE child_id = %s
				ORDER BY weight DESC
			""", object_id))
		while(recurse):
			ancestor_ids = self.pool.runQuery(sql.interp(
				"""SELECT parent_id AS id
					FROM object_relation
					WHERE child_id IN %s
					ORDER BY weight DESC
				""", [x['id'] for x in ancestor_ids]))
			if(ancestor_ids):
				parent_ids.extend(ancestor_ids)
			else:
				recurse = False
		return self.instantiate('object', *parent_ids)
	
	def remove_parent(self, child_id, parent_id):
		self.pool.runOperation("DELETE FROM object_relation WHERE child_id = %s AND parent_id = %s", child_id, parent_id)
	
	def add_parent(self, child_id, parent_id):
		self.pool.runOperation("INSERT INTO object_relation (child_id, parent_id) VALUES (%s, %s)", child_id, parent_id)
	
	def has(self, origin_id, item_type, name, recurse=True, unrestricted=True):
		item = getattr(self, 'get_%s' % item_type, lambda *x: None)(origin_id, name, recurse)
		if(item is None):
			return False
		
		if(item_type == 'verb'):
			return unrestricted or item.is_executable()
		elif(item_type == 'property'):
			return unrestricted or item.is_readable()
		
		raise ValueError("Unknown item type, '%s'." % item_type)
	
	def get_ancestor_with(self, descendent_id, attribute_type, name):
		if(attribute_type not in ('property', 'verb')):
			raise ValueError("Invalid attribute type: %s" % type)
		
		a = None
		parents = [descendent_id]
		while(parents):
			object_id = parents.pop(0)
			if(attribute_type == 'verb'):
				a = self.pool.runQuery(sql.interp(
					"""SELECT v.origin_id AS id
						 FROM verb v
							INNER JOIN verb_name vn ON v.id = vn.verb_id
						WHERE vn.name = %s
						  AND v.origin_id = %s
					""", name, object_id))
			elif(attribute_type == 'property'):
				a = self.pool.runQuery(sql.interp(
					"""SELECT p.origin_id AS id
						 FROM property p
						WHERE p.name = %s
						 AND p.origin_id = %s
					""" % name, object_id))
			
			if not(a):
				results = self.pool.runQuery(sql.interp("SELECT parent_id FROM object_relation WHERE child_id = %s", parent_id))
				parents.extend([result['parent_id'] for result in results])
		
		if not(a):
			return None
		
		return self.instantiate('object', a[0])
	
	def get_verb(self, origin_id, name, recurse=True):
		v = None
		parents = [origin_id]
		while(parents):
			parent_id = parents.pop(0)
			v = self.pool.runQuery(sql.interp(
				"""SELECT v.*
					FROM verb v
						INNER JOIN verb_name vn ON vn.verb_id = v.id
					WHERE vn.name = %s
					  AND v.origin_id = %s
				""", name, parent_id))
			if(not v and recurse):
				results = self.pool.runQuery(sql.interp("SELECT parent_id FROM object_relation WHERE child_id = %s", parent_id))
				parents.extend([result['parent_id'] for result in results])

		if not(v):
			return None
		
		return self.instantiate('verb', v[0])
	
	def get_verb_names(self, verb_id):
		result = self.pool.runQuery(sql.interp("SELECT name FROM verb_name WHERE verb_id = %s", verb_id))
		return [x['name'] for x in result]
	
	def add_verb_name(self, verb_id, name):
		self.pool.runOperation(sql.build_insert('verb_name', verb_id=verb_id, name=name))
	
	def remove_verb_name(self, verb_id, name):
		self.pool.runOperation(sql.build_delete('verb_name', verb_id=verb_id, name=name))
	
	def get_property(self, origin_id, name, recurse=True):
		p = None
		parents = [origin_id]
		while(parents):
			parent_id = parents.pop(0)
			p = self.pool.runQuery(sql.interp(
				"""SELECT p.*
					FROM property p
					WHERE p.name = %s
					  AND p.origin_id = %s
				""", name, parent_id))
			if(not p and recurse):
				results = self.pool.runQuery(sql.interp("SELECT parent_id FROM object_relation WHERE child_id = %s", parent_id))
				parents.extend([result['parent_id'] for result in results])
		
		if not(p):
			return None
		
		return self.instantiate('property', p[0])
	
	def refs(self, key):
		"""
		How many objects in the store share the name given?
		"""
		result = self.pool.runQuery(sql.interp("SELECT COUNT(*) AS count FROM object WHERE name = %s", key))
		return result[0]['count']
	
	def is_unique_name(self, key):
		result = self.pool.runQuery(sql.build_select('object', dict(
			name		= sql.RAW(sql.interp('LOWER(%%s) = LOWER(%s)', key)),
			unique_name	= True
		)))
		return bool(result)
	
	def remove(self, obj_type, object_id):
		self.pool.runOperation(sql.build_delete(obj_type, id=object_id))
		self.cache.pop('%s-%s' % (obj_type, object_id), None)
	
	def is_player(self, object_id):
		result = self.pool.runQuery(sql.interp("SELECT id FROM player WHERE avatar_id = %s", object_id))
		return bool(len(result))
	
	def is_connected_player(self, avatar_id):
		result = self.pool.runQuery(sql.interp(
			"""SELECT 1
				 FROM player
				WHERE COALESCE(last_login, to_timestamp(0)) > COALESCE(last_logout, to_timestamp(0))
				  AND avatar_id = %s
			""", avatar_id))
		return bool(result)
	
	def set_player(self, object_id, is_player, passwd=None):
		player_mode = self.is_player(object_id)
		if(is_player and not(player_mode)):
			salt = 've' # TODO: make this random
			c = crypt.crypt(passwd, salt)
			self.pool.runOperation(sql.build_insert('player', dict(avatar_id=object_id, crypt=c)))
		elif(not is_player and player_mode):
			self.pool.runOperation(sql.build_delete('player', dict(avatar_id=object_id)))
	
	def login_player(self, avatar_id):
		self.pool.runOperation(sql.build_update('player', dict(last_login=sql.RAW('now()')), dict(avatar_id=avatar_id)))
	
	def logout_player(self, avatar_id):
		self.pool.runOperation(sql.build_update('player', dict(last_logout=sql.RAW('now()')), dict(avatar_id=avatar_id)))
	
	def get_contents(self, container_id, recurse=False):
		nested_location_ids = location_ids = self.pool.runQuery(sql.interp(
			"""SELECT id
				FROM object
				WHERE location_id = %s
			""", container_id))
		while(recurse):
			location_ids = self.pool.runQuery(sql.interp(
				"""SELECT id
					FROM object
					WHERE location_id IN %s
				""", [x['id'] for x in location_ids]))
			if(location_ids):
				nested_location_ids.extend(location_ids)
			else:
				recurse = False
		return self.instantiate('object', *nested_location_ids)
	
	def find(self, container_id, name):
		match_ids = self.pool.runQuery(sql.interp(
			"""SELECT id
				FROM object
				WHERE LOWER(name) = LOWER(%s)
				  AND location_id = %s
			""", name, container_id))
		
		match_ids.extend(self.pool.runQuery(sql.interp(
			"""SELECT o.id
				FROM property p
					INNER JOIN object o ON p.origin_id = o.id
				WHERE p.name = 'name'
				  AND LOWER(p.value) = LOWER(%s)
				  AND o.location_id = %s
			""", name, container_id)))
		
		match_ids.extend(self.pool.runQuery(sql.interp(
			"""SELECT o.id
				FROM object o
					INNER JOIN object_alias oa ON oa.object_id = o.id
				WHERE LOWER(oa.alias) = LOWER(%s)
				  AND o.location_id = %s
			""", name, container_id)))
		
		return self.instantiate('object', *match_ids)
	
	def contains(self, container_id, object_id, recurse=False):
		location_ids = self.pool.runQuery(sql.interp(
			"""SELECT id
				FROM object
				WHERE location_id = %s
				ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
			""", container_id, object_id))
		
		if(location_ids and location_ids[0]['id'] == object_id):
			return True
		
		while(recurse):
			container_ids = [x['id'] for x in location_ids]
			if(container_ids):
				location_ids = self.pool.runQuery(sql.interp(
					"""SELECT id
						FROM object
						WHERE location_id IN %s
						ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
					""", container_ids, object_id))
			if(location_ids):
				if(location_ids[0]['id'] == object_id):
					return True
			else:
				recurse = False
		
		return False
	
	def is_allowed(self, object_id, permission, subject_type, subject_id):
		query = dict()
		if(subject_type == 'object'):
			query['object_id'] = subject_id
		elif(subject_type == 'verb'):
			query['verb_id'] = subject_id
		elif(subject_type == 'property'):
			query['property_id'] = subject_id
		
		query['__order_by'] = "rule"
		
		access_query = sql.build_select('access', query)
		return True
		
		# rule allow/deny
		# permission_id
		# 
		# type accessor/group
		# group
	
	def validate_password(self, object_id, password):
		saved_crypt = self.pool.runQuery(sql.interp(
			"""SELECT crypt
				FROM player
				WHERE avatar_id = %s
			""", object_id))
		if not(saved_crypt):
			return False
		
		saved_crypt = saved_crypt[0]['crypt']
		
		return crypt.crypt(password, saved_crypt[0:2]) == saved_crypt
