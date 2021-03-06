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


class Halibot():

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

	def add_instance(self, name, inst):
		self.objects[name] = inst
		inst.name = name
		inst.init()
		self.log.info("Instantiated object '" + name + "'")

	def _load_config(self):
		with open("config.json","r") as f:
			self.config = json.loads(f.read())
			halibot.packages.__path__ = self.config.get("package-path", [])

	def _get_class_from_package(self, pkgname, clsname):
		pkg = self.get_package(pkgname)
		if pkg == None:
			self.log.error("Cannot find package {}!".format(pkgname))
			return None

		obj = getattr(pkg, clsname, None)
		if obj == None:
			self.log.error("Cannot find class {} in package {}!".format(clsname, pkgname))
			return None

		return obj

	def _instantiate_objects(self, key):
		inst = self.config[key + "-instances"]

		for k in inst.keys():
			# TODO include directive

			conf = inst[k]
			split = conf["of"].split(":")

			if len(split) == 2:
				obj = self._get_class_from_package(split[0], split[1])
			else:
				self.log.error("Invalid class identifier {}, must contain only 1 ':'".format(conf["of"]))
				continue

			self.add_instance(k, obj(self, conf))

	def get_package(self, name):
		return importlib.import_module('halibot.packages.' + name)

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
