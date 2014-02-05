#
#

# Copyright (C) 2007, 2008 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

"""Serializer abstraction module

This module introduces a simple abstraction over the serialization
backend (currently json).

"""
# pylint: disable=C0103

# C0103: Invalid name, since pylint doesn't see that Dump points to a
# function and not a constant

import re

# Python 2.6 and above contain a JSON module based on simplejson. Unfortunately
# the standard library version is significantly slower than the external
# module. While it should be better from at least Python 3.2 on (see Python
# issue 7451), for now Ganeti needs to work well with older Python versions
# too.
import simplejson

from ganeti import errors
from ganeti import utils
from ganeti import constants

_RE_EOLSP = re.compile("[ \t]+$", re.MULTILINE)


def DumpJson(data, private_decoder=None):
  """Serialize a given object.

  @param data: the data to serialize
  @return: the string representation of data

  """
  if private_decoder is None:
    # Do not leak private fields by default.
    private_decoder = EncodeWithoutPrivate
  encoded = simplejson.dumps(data, default=private_decoder)

  txt = _RE_EOLSP.sub("", encoded)
  if not txt.endswith("\n"):
    txt += "\n"

  return txt


def LoadJson(txt):
  """Unserialize data from a string.

  @param txt: the json-encoded form

  @return: the original data

  """
  values = simplejson.loads(txt)

  # Hunt and seek for Private fields and wrap them.
  WrapPrivateValues(values)

  return values


def WrapPrivateValues(json):
  todo = [json]

  while todo:
    data = todo.pop()

    if isinstance(data, list): # Array
      for item in data:
        todo.append(item)
    elif isinstance(data, dict): # Object

      # This is kind of a kludge, but the only place where we know what should
      # be protected is in opcodes.py, and not in a way that is helpful to us,
      # especially in such a high traffic method; on the other hand, the
      # Haskell `py_compat_fields` test should complain whenever this check
      # does not protect fields properly.
      for field in data:
        value = data[field]
        if field in constants.PRIVATE_PARAMETERS_BLACKLIST:
          if not field.endswith("_cluster"):
            data[field] = PrivateDict(value)
          else:
            for os in data[field]:
              value[os] = PrivateDict(value[os])
        else:
          todo.append(value)
    else: # Values
      pass


def DumpSignedJson(data, key, salt=None, key_selector=None,
                   private_decoder=None):
  """Serialize a given object and authenticate it.

  @param data: the data to serialize
  @param key: shared hmac key
  @param key_selector: name/id that identifies the key (in case there are
    multiple keys in use, e.g. in a multi-cluster environment)
  @return: the string representation of data signed by the hmac key

  """
  txt = DumpJson(data, private_decoder=private_decoder)
  if salt is None:
    salt = ""
  signed_dict = {
    "msg": txt,
    "salt": salt,
    }

  if key_selector:
    signed_dict["key_selector"] = key_selector
  else:
    key_selector = ""

  signed_dict["hmac"] = utils.Sha1Hmac(key, txt, salt=salt + key_selector)

  return DumpJson(signed_dict)


def LoadSignedJson(txt, key):
  """Verify that a given message was signed with the given key, and load it.

  @param txt: json-encoded hmac-signed message
  @param key: the shared hmac key or a callable taking one argument (the key
    selector), which returns the hmac key belonging to the key selector.
    Typical usage is to pass a reference to the get method of a dict.
  @rtype: tuple of original data, string
  @return: original data, salt
  @raises errors.SignatureError: if the message signature doesn't verify

  """
  signed_dict = LoadJson(txt)

  WrapPrivateValues(signed_dict)

  if not isinstance(signed_dict, dict):
    raise errors.SignatureError("Invalid external message")
  try:
    msg = signed_dict["msg"]
    salt = signed_dict["salt"]
    hmac_sign = signed_dict["hmac"]
  except KeyError:
    raise errors.SignatureError("Invalid external message")

  if callable(key):
    # pylint: disable=E1103
    key_selector = signed_dict.get("key_selector", None)
    hmac_key = key(key_selector)
    if not hmac_key:
      raise errors.SignatureError("No key with key selector '%s' found" %
                                  key_selector)
  else:
    key_selector = ""
    hmac_key = key

  if not utils.VerifySha1Hmac(hmac_key, msg, hmac_sign,
                              salt=salt + key_selector):
    raise errors.SignatureError("Invalid Signature")

  return LoadJson(msg), salt


def LoadAndVerifyJson(raw, verify_fn):
  """Parses and verifies JSON data.

  @type raw: string
  @param raw: Input data in JSON format
  @type verify_fn: callable
  @param verify_fn: Verification function, usually from L{ht}
  @return: De-serialized data

  """
  try:
    data = LoadJson(raw)
  except Exception, err:
    raise errors.ParseError("Can't parse input data: %s" % err)

  if not verify_fn(data):
    raise errors.ParseError("Data does not match expected format: %s" %
                            verify_fn)

  return data


Dump = DumpJson
Load = LoadJson
DumpSigned = DumpSignedJson
LoadSigned = LoadSignedJson


class Private(object):

  def __init__(self, item, descr="redacted"):
    if isinstance(item, Private):
      raise ValueError("Attempted to nest Private values.")
    self._item = item
    self._descr = descr

  def Get(self):
    return self._item

  def __str__(self):
    return "<{._descr}>".format(self)

  def __repr__(self):
    return "Private(?, descr='{._descr}')".format(self)

  # pylint: disable=W0212
  # If it doesn't access _item directly, the call will go through __getattr__
  # because this class defines __slots__ and "item" is not in it.
  # OTOH, if we do add it there, we'd risk shadowing an "item" attribute.
  def __eq__(self, other):
    if isinstance(other, Private):
      return self._item == other._item
    else:
      return self._item == other

  def __hash__(self):
    return hash(self._item)

  def __format__(self, *_1, **_2):
    return self.__str__()

  def __getattr__(self, attr):
    return Private(getattr(self._item, attr),
                   descr="%s.%s" % (self._descr, attr))

  def __call__(self, *args, **kwargs):
    return Private(self._item(*args, **kwargs),
                   descr="%s()" % self._descr)

  # pylint: disable=R0201
  # While this could get away with being a function, it needs to be a method.
  # Required by the copy.deepcopy function used by FillDict.
  def __getnewargs__(self):
    return tuple()

  def __nonzero__(self):
    return bool(self._item)

  # Get in the way of Pickle by implementing __slots__ but not __getstate__
  # ...and get a performance boost, too.
  __slots__ = ["_item", "_descr"]


class PrivateDict(dict):
  """A dictionary that turns its values to private fields.

    >>> PrivateDict()
    {}
    >>> supersekkrit = PrivateDict({"password": "foobar"})
    >>> supersekkrit["password"]
    Private(?, descr='password')
    >>> supersekkrit["password"].Get()
    'foobar'
    >>> supersekkrit["user"] = "eggspam"
    >>> supersekkrit.GetPrivate("user")
    'eggspam'
    >>> supersekkrit.Unprivate()
    {'password': 'foobar', 'user': 'eggspam'}

  """

  def __init__(self, data=None):
    dict.__init__(self)
    self.update(data)

  def __setitem__(self, item, value):
    if not isinstance(value, Private):
      if not isinstance(item, dict):
        value = Private(value, descr=item)
      else:
        value = PrivateDict(value)
    dict.__setitem__(self, item, value)

  # The actual conversion to Private containers is done by __setitem__

  # copied straight from cpython/Lib/UserDict.py
  # Copyright (c) 2001-2014 Python Software Foundation; All Rights Reserved
  def update(self, other=None, **kwargs):
    # Make progressively weaker assumptions about "other"
    if other is None:
      pass
    elif hasattr(other, 'iteritems'):  # iteritems saves memory and lookups
      for k, v in other.iteritems():
        self[k] = v
    elif hasattr(other, 'keys'):
      for k in other.keys():
        self[k] = other[k]
    else:
      for k, v in other:
        self[k] = v
    if kwargs:
      self.update(kwargs)

  def GetPrivate(self, *args):
    """Like dict.get, but extracting the value in the process.

    Arguments are semantically equivalent to dict.get

      >>> PrivateDict({"foo": "bar"}).GetPrivate("foo")
      'bar'
      >>> PrivateDict({"foo": "bar"}).GetPrivate("baz", "spam")
      'spam'

    """ # epydoc does not check doctests, btw.
    if len(args) == 1:
      key, = args
      return self[key].Get()
    elif len(args) == 2:
      key, default = args
      if key not in self:
        return default
      else:
        return self[key].Get()
    else:
      raise TypeError("GetPrivate() takes 2 arguments (%d given)" % len(args))

  def Unprivate(self):
    """Turn this dict of Private() values to a dict of values.

    >>> PrivateDict({"foo": "bar"}).Unprivate()
    {'foo': 'bar'}

    @rtype: dict

    """
    returndict = {}
    for key in self:
      returndict[key] = self[key].Get()
    return returndict


def EncodeWithoutPrivate(obj):
  if isinstance(obj, Private):
    return None
  raise TypeError(repr(obj) + " is not JSON serializable")


def EncodeWithPrivateFields(obj):
  if isinstance(obj, Private):
    return obj.Get()
  raise TypeError(repr(obj) + " is not JSON serializable")
