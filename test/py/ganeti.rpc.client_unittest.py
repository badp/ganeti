#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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


"""Script for unittesting the RPC client module"""


import unittest

from ganeti import constants
from ganeti import errors
from ganeti import serializer
from ganeti.rpc import client

import testutils


class TextRPCParsing(testutils.GanetiTestCase):
  def testParseRequest(self):
    msg = serializer.DumpJson({
      client.KEY_METHOD: "foo",
      client.KEY_ARGS: ("bar", "baz", 123),
      })

    self.assertEqualValues(client.ParseRequest(msg),
                           ("foo", ["bar", "baz", 123], None))

    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      "this\"is {invalid, ]json data")

    # No dict
    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      serializer.DumpJson(123))

    # Empty dict
    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      serializer.DumpJson({ }))

    # No arguments
    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      serializer.DumpJson({ client.KEY_METHOD: "foo", }))

    # No method
    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      serializer.DumpJson({ client.KEY_ARGS: [], }))

    # No method or arguments
    self.assertRaises(client.ProtocolError, client.ParseRequest,
                      serializer.DumpJson({ client.KEY_VERSION: 1, }))

  def testParseRequestWithVersion(self):
    msg = serializer.DumpJson({
      client.KEY_METHOD: "version",
      client.KEY_ARGS: (["some"], "args", 0, "here"),
      client.KEY_VERSION: 20100101,
      })

    self.assertEqualValues(client.ParseRequest(msg),
                           ("version", [["some"], "args", 0, "here"], 20100101))

  def testParseResponse(self):
    msg = serializer.DumpJson({
      client.KEY_SUCCESS: True,
      client.KEY_RESULT: None,
      })

    self.assertEqual(client.ParseResponse(msg), (True, None, None))

    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      "this\"is {invalid, ]json data")

    # No dict
    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      serializer.DumpJson(123))

    # Empty dict
    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      serializer.DumpJson({ }))

    # No success
    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      serializer.DumpJson({ client.KEY_RESULT: True, }))

    # No result
    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      serializer.DumpJson({ client.KEY_SUCCESS: True, }))

    # No result or success
    self.assertRaises(client.ProtocolError, client.ParseResponse,
                      serializer.DumpJson({ client.KEY_VERSION: 123, }))

  def testParseResponseWithVersion(self):
    msg = serializer.DumpJson({
      client.KEY_SUCCESS: True,
      client.KEY_RESULT: "Hello World",
      client.KEY_VERSION: 19991234,
      })

    self.assertEqual(client.ParseResponse(msg), (True, "Hello World", 19991234))

  def testFormatResponse(self):
    for success, result in [(False, "error"), (True, "abc"),
                            (True, { "a": 123, "b": None, })]:
      msg = client.FormatResponse(success, result)
      msgdata = serializer.LoadJson(msg)
      self.assert_(client.KEY_SUCCESS in msgdata)
      self.assert_(client.KEY_RESULT in msgdata)
      self.assert_(client.KEY_VERSION not in msgdata)
      self.assertEqualValues(msgdata,
                             { client.KEY_SUCCESS: success,
                               client.KEY_RESULT: result,
                             })

  def testFormatResponseWithVersion(self):
    for success, result, version in [(False, "error", 123), (True, "abc", 999),
                                     (True, { "a": 123, "b": None, }, 2010)]:
      msg = client.FormatResponse(success, result, version=version)
      msgdata = serializer.LoadJson(msg)
      self.assert_(client.KEY_SUCCESS in msgdata)
      self.assert_(client.KEY_RESULT in msgdata)
      self.assert_(client.KEY_VERSION in msgdata)
      self.assertEqualValues(msgdata,
                             { client.KEY_SUCCESS: success,
                               client.KEY_RESULT: result,
                               client.KEY_VERSION: version,
                             })

  def testFormatRequest(self):
    for method, args in [("a", []), ("b", [1, 2, 3])]:
      msg = client.FormatRequest(method, args)
      msgdata = serializer.LoadJson(msg)
      self.assert_(client.KEY_METHOD in msgdata)
      self.assert_(client.KEY_ARGS in msgdata)
      self.assert_(client.KEY_VERSION not in msgdata)
      self.assertEqualValues(msgdata,
                             { client.KEY_METHOD: method,
                               client.KEY_ARGS: args,
                             })

  def testFormatRequestWithVersion(self):
    for method, args, version in [("fn1", [], 123), ("fn2", [1, 2, 3], 999)]:
      msg = client.FormatRequest(method, args, version=version)
      msgdata = serializer.LoadJson(msg)
      self.assert_(client.KEY_METHOD in msgdata)
      self.assert_(client.KEY_ARGS in msgdata)
      self.assert_(client.KEY_VERSION in msgdata)
      self.assertEqualValues(msgdata,
                             { client.KEY_METHOD: method,
                               client.KEY_ARGS: args,
                               client.KEY_VERSION: version,
                             })


class TestCallRPCMethod(unittest.TestCase):
  MY_LUXI_VERSION = 1234
  assert constants.LUXI_VERSION != MY_LUXI_VERSION

  def testSuccessNoVersion(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fn1")
      self.assertEqual(args, "Hello World")
      return client.FormatResponse(True, "x")

    result = client.CallRPCMethod(_Cb, "fn1", "Hello World")

  def testServerVersionOnly(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fn1")
      self.assertEqual(args, "Hello World")
      return client.FormatResponse(True, "x", version=self.MY_LUXI_VERSION)

    self.assertRaises(errors.LuxiError, client.CallRPCMethod,
                      _Cb, "fn1", "Hello World")

  def testWithVersion(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fn99")
      self.assertEqual(args, "xyz")
      return client.FormatResponse(True, "y", version=self.MY_LUXI_VERSION)

    self.assertEqual("y", client.CallRPCMethod(_Cb, "fn99", "xyz",
                                              version=self.MY_LUXI_VERSION))

  def testVersionMismatch(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fn5")
      self.assertEqual(args, "xyz")
      return client.FormatResponse(True, "F", version=self.MY_LUXI_VERSION * 2)

    self.assertRaises(errors.LuxiError, client.CallRPCMethod,
                      _Cb, "fn5", "xyz", version=self.MY_LUXI_VERSION)

  def testError(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fnErr")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("Test")
      return client.FormatResponse(False, errors.EncodeException(err))

    self.assertRaises(errors.OpPrereqError, client.CallRPCMethod,
                      _Cb, "fnErr", [])

  def testErrorWithVersionMismatch(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fnErr")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("TestVer")
      return client.FormatResponse(False, errors.EncodeException(err),
                                 version=self.MY_LUXI_VERSION * 2)

    self.assertRaises(errors.LuxiError, client.CallRPCMethod,
                      _Cb, "fnErr", [],
                      version=self.MY_LUXI_VERSION)

  def testErrorWithVersion(self):
    def _Cb(msg):
      (method, args, version) = client.ParseRequest(msg)
      self.assertEqual(method, "fn9")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("TestVer")
      return client.FormatResponse(False, errors.EncodeException(err),
                                 version=self.MY_LUXI_VERSION)

    self.assertRaises(errors.OpPrereqError, client.CallRPCMethod,
                      _Cb, "fn9", [],
                      version=self.MY_LUXI_VERSION)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
