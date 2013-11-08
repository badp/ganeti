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

"""Script for unittesting the ganeti.storage.gluster module"""

import os
import shutil
import tempfile
import unittest
import mock

from ganeti import errors
from ganeti.storage import filestorage
from ganeti.storage import gluster
from ganeti import utils

import testutils

class TestGlusterVolume(testutils.GanetiTestCase):

  @classmethod
  def makeVolume(cls, ipv=4, addr=None, port=9001,
                 run_cmd=NotImplemented,
                 vol_name="pinky"):

    address = {4: "74.65.28.66",
               6: "74:65::28:6:69",
              } # T9

    return gluster.GlusterVolume(address[ipv] if not addr else addr,
                                 port,
                                 str(vol_name),
                                 _run_cmd=run_cmd
                                )

    TestGlusterVolume.last_vol_name = vol_name

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    # Create some volumes.
    self.vol_a = TestGlusterVolume.makeVolume()
    self.vol_a_clone = TestGlusterVolume.makeVolume()
    self.vol_b = TestGlusterVolume.makeVolume(vol_name="pinker")

  def testEquality(self):
    self.assertEqual(self.vol_a, self.vol_a_clone)

  def testInequality(self):
    self.assertNotEqual(self.vol_a, self.vol_b)

  def testHostnameResolution(self):
    vol_1 = TestGlusterVolume.makeVolume(addr="localhost")
    self.assertEqual(vol_1.server_ip, "127.0.0.1")
    with self.assertRaises(errors.ResolverError):
      TestGlusterVolume.makeVolume(addr="E_NOENT")

  def testURIs(self):
    # The only source of documentation I can find is:
    #   https://github.com/qemu/qemu/commit/8d6d89c
    # This test gets as close as possible to the examples given there,
    # within the limits of our implementation (no transport specification,
    #                                          no default port version).

    vol_1 = TestGlusterVolume.makeVolume(addr="1.2.3.4",
                                         port=24007,
                                         vol_name="testvol")
    self.assertEqual(vol_1.GetKVMMountString("dir/a.img"),
                     "gluster://1.2.3.4:24007/testvol/dir/a.img")
    self.assertEqual(vol_1._GetFUSEMountString(),
                     "1.2.3.4:24007:testvol")
    self.assertEqual(vol_1._GetMtabString(),
                     "1.2.3.4:testvol")

    vol_2 = TestGlusterVolume.makeVolume(addr="1:2:3:4:5::8",
                                         port=24007,
                                         vol_name="testvol")
    self.assertEqual(vol_2.GetKVMMountString("dir/a.img"),
                     "gluster://[1:2:3:4:5::8]:24007/testvol/dir/a.img")
    # This _ought_ to work. https://bugzilla.redhat.com/show_bug.cgi?id=764188
    self.assertEqual(vol_2._GetFUSEMountString(),
                     "1:2:3:4:5::8:24007:testvol")
    self.assertEqual(vol_2._GetMtabString(),
                     "1:2:3:4:5::8:testvol")

    # Technically KVM could do name resolution on its own, but we don't do that
    # for mount point deduplication purposes.
    vol_3 = TestGlusterVolume.makeVolume(addr="localhost",
                                         port=9001,
                                         vol_name="testvol")
    self.assertEqual(vol_3.GetKVMMountString("dir/a.img"),
                     "gluster://127.0.0.1:9001/testvol/dir/a.img")
    self.assertEqual(vol_3._GetFUSEMountString(),
                     "127.0.0.1:9001:testvol")
    self.assertEqual(vol_3._GetMtabString(),
                     "127.0.0.1:testvol")

if __name__ == "__main__":
  testutils.GanetiTestProgram()
