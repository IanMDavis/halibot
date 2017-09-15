#
# Main bot class
#    Handles routing, config, agent/module loading
#
import json
import threading
import os, sys
import importlib
import halibot.packages
from queue import Queue,Empty
from .halmodule import HalModule
from .halagent import HalAgent
from .halauth import HalAuth
from .loader import Loader

# Avoid appending "." if it i
if "." not in sys.path:
	sys.path.append(".")
import logging

class ObjectDict(dict):

	@property
	def modules(self):
		return dict(filter(lambda x: isinstance(x[1], HalModule), self.items()))

	@property
	def agents(self):
		return dict(filter(lambda x: isinstance(x[1], HalAgent), self.items()))


class Version():
	def __init__(self, val):
		v = val.split(".")
		self.major = int(v[0])
		self.minor = int(v[1])
		self.patch = int(v[2]) if len(v) == 3 else 0

	def __ge__(self, other):
		return self._eq(other) >= 0

	def __le__(self, other):
		return self._eq(other) <= 0

	def __gt__(self, other):
		return self._eq(other) > 0

	def __lt__(self, other):
		return self._eq(other) < 0

	def __eq__(self, other):
		return not self._eq(other)

	# C-like comparator that returns 0 if equal, negative value if less, positive if greater
	def _eq(self, other):
		ret = self.major - other.major
		if ret:
			return ret
		ret = self.minor - other.minor
		if ret:
			return ret
		return self.patch - other.patch


class Halibot():

	VERSION = "0.1.0"

	config = {}

	running = False
	log = None

	def __init__(self, **kwargs):
		self.log = logging.getLogger(self.__class__.__name__)

		self.use_config = kwargs.get("use_config", True)
		self.use_auth = kwargs.get("use_auth", True)

		self.auth = HalAuth()
		self.objects = ObjectDict()

	# Start the Hal instance
	def start(self, block=True):
		self.running = True

		if self.use_config:
			self._load_config()
			self._instantiate_objects("agent")
			self._instantiate_objects("module")
			if self.use_auth:
				self.auth.load_perms(self.config.get("auth-path","permissions.json"))

	def shutdown(self):
		self.log.info("Shutting down halibot...");

		for o in self.objects.values():
			o._shutdown()

		self.log.info("Halibot shutdown. Threads left: " + str(threading.active_count()))

	def _check_version(self, obj):
		v = Version(self.VERSION)
		if not hasattr(obj, "HAL_MINIMUM"):
			self.log.warn("Module class '{}' does not define a minimum version, trying to load anyway...".format(obj.__class__.__name__))
			return True

		if v < Version(obj.HAL_MINIMUM):
			self.log.error("Rejecting load of '{}', requires minimum Halibot version '{}'. (Currently running '{}')".format(obj.__class__.__name__, obj.HAL_MINIMUM, self.VERSION))
			return False

		if hasattr(obj, "HAL_MAXIMUM"):
			if v <= Version(obj.HAL_MAXIMUM):
				self.log.error("Rejecting load of '{}', requires maximum Halibot version '{}'. (Currently running '{}')".format(obj.__class__.__name__, inst.HAL_MAXIMUM, self.VERSION))
				return False
		return True

	def add_instance(self, name, inst):
		self.objects[name] = inst
		inst.name = name
		inst.init()
		self.log.info("Instantiated object '" + name + "'")

	def _load_config(self):
		with open("config.json","r") as f:
			self.config = json.loads(f.read())
			halibot.packages.__path__ = self.config.get("package-path", [])

			# Deprecated; remove with 1.0
			self.agent_loader = Loader(self.config["package-path"], HalAgent)
			self.module_loader = Loader(self.config["package-path"], HalModule)


	def _get_class_from_package(self, pkgname, clsname):
		pkg = self.get_package(pkgname)
		if pkg == None:
			self.log.error("Cannot find package {}!".format(pkgname))
			return None

		obj = getattr(pkg, clsname, None)
		if obj == None:
			self.log.error("Cannot find class {} in package {}!".format(clsname, pkgname))
			return None

		if not self._check_version(obj):
			return None

		return obj

	def _instantiate_objects(self, key):
		inst = self.config[key + "-instances"]

		for k in inst.keys():
			# TODO include directive

			conf = inst[k]
			split = conf["of"].split(":")

			if len(split) == 1:
				# deprecated; remove with 1.0
				if key == "modules":
					obj = self.module_loader.get(conf["of"])
				else:
					obj = self.agent_loader.get(conf["of"])
			elif len(split) == 2:
				obj = self._get_class_from_package(split[0], split[1])
			else:
				self.log.error("Invalid class identifier {}, must contain only 1 ':'".format(conf["of"]))
				continue

			if not obj:
				self.log.error("Failed to obtain the class for '{}', skipping...".format(k))
				continue

			self.add_instance(k, obj(self, conf))

	def get_package(self, name):
		return importlib.import_module('halibot.packages.' + name)

	# TODO: Reload a class, and restart all modules of that class
	def reload(self, name):
		parent = 'halibot.packages.' + name
		for k,o in self.objects.items():
			if o.__module__.startswith(parent + '.') or o.__module__ == parent:
				o._shutdown()
				mod = importlib.reload(importlib.import_module(o.__module__))
				cls = getattr(mod, o.__class__.__name__)
				self.add_instance(k, cls(self, o.config))



	# Restart a module instance by name
	def restart(self, name):
		o = self.objects.get(name)
		if o:
			o.shutdown()
			o.init()
		else:
			self.log.warning("Failed to restart instance '{}'".format(name))
