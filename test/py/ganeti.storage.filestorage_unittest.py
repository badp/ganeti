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


"""Script for unittesting the ganeti.storage.file module"""

import os
import shutil
import tempfile
import unittest

from ganeti import errors
from ganeti.storage import filestorage
from ganeti import utils

import testutils


class TestFileStorageSpaceInfo(unittest.TestCase):

  def testSpaceInfoPathInvalid(self):
    """Tests that an error is raised when the given path is not existing.

    """
    self.assertRaises(errors.CommandError, filestorage.GetFileStorageSpaceInfo,
                      "/path/does/not/exist/")

  def testSpaceInfoPathValid(self):
    """Smoke test run on a directory that exists for sure.

    """
    filestorage.GetFileStorageSpaceInfo("/")


class TestCheckFileStoragePath(unittest.TestCase):
  def _WriteAllowedFile(self, allowed_paths_filename, allowed_paths):
    allowed_paths_file = open(allowed_paths_filename, 'w')
    allowed_paths_file.write('\n'.join(allowed_paths))
    allowed_paths_file.close()

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.allowed_paths = [os.path.join(self.tmpdir, "allowed")]
    for path in self.allowed_paths:
      os.mkdir(path)
    self.allowed_paths_filename = os.path.join(self.tmpdir, "allowed-path-file")
    self._WriteAllowedFile(self.allowed_paths_filename, self.allowed_paths)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCheckFileStoragePathExistance(self):
    filestorage._CheckFileStoragePathExistance(self.tmpdir)

  def testCheckFileStoragePathExistanceFail(self):
    path = os.path.join(self.tmpdir, "does/not/exist")
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)

  def testCheckFileStoragePathNotWritable(self):
    path = os.path.join(self.tmpdir, "isnotwritable/")
    os.mkdir(path)
    os.chmod(path, 0)
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)
    os.chmod(path, 777)

  def testCheckFileStoragePath(self):
    path = os.path.join(self.allowed_paths[0], "allowedsubdir")
    os.mkdir(path)
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertEqual(None, result)

  def testCheckFileStoragePathNotAllowed(self):
    path = os.path.join(self.tmpdir, "notallowed")
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertTrue("not acceptable" in result)


class TestLoadAllowedFileStoragePaths(testutils.GanetiTestCase):
  def testDevNull(self):
    self.assertEqual(filestorage._LoadAllowedFileStoragePaths("/dev/null"), [])

  def testNonExistantFile(self):
    filename = "/tmp/this/file/does/not/exist"
    assert not os.path.exists(filename)
    self.assertEqual(filestorage._LoadAllowedFileStoragePaths(filename), [])

  def test(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      # This is a test file
      /tmp
      /srv/storage
      relative/path
      """)

    self.assertEqual(filestorage._LoadAllowedFileStoragePaths(tmpfile), [
      "/tmp",
      "/srv/storage",
      "relative/path",
      ])


class TestComputeWrongFileStoragePathsInternal(unittest.TestCase):
  def testPaths(self):
    paths = filestorage._GetForbiddenFileStoragePaths()

    for path in ["/bin", "/usr/local/sbin", "/lib64", "/etc", "/sys"]:
      self.assertTrue(path in paths)

    self.assertEqual(set(map(os.path.normpath, paths)), paths)

  def test(self):
    vfsp = filestorage._ComputeWrongFileStoragePaths
    self.assertEqual(vfsp([]), [])
    self.assertEqual(vfsp(["/tmp"]), [])
    self.assertEqual(vfsp(["/bin/ls"]), ["/bin/ls"])
    self.assertEqual(vfsp(["/bin"]), ["/bin"])
    self.assertEqual(vfsp(["/usr/sbin/vim", "/srv/file-storage"]),
                     ["/usr/sbin/vim"])


class TestComputeWrongFileStoragePaths(testutils.GanetiTestCase):
  def test(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      /tmp
      x/y///z/relative
      # This is a test file
      /srv/storage
      /bin
      /usr/local/lib32/
      relative/path
      """)

    self.assertEqual(
        filestorage.ComputeWrongFileStoragePaths(_filename=tmpfile),
        ["/bin",
         "/usr/local/lib32",
         "relative/path",
         "x/y/z/relative",
        ])


class TestCheckFileStoragePathInternal(unittest.TestCase):
  def testNonAbsolute(self):
    for i in ["", "tmp", "foo/bar/baz"]:
      self.assertRaises(errors.FileStoragePathError,
                        filestorage._CheckFileStoragePath, i, ["/tmp"])

    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp", ["tmp", "xyz"])

  def testNoAllowed(self):
    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp", [])

  def testNoAdditionalPathComponent(self):
    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp/foo",
                      ["/tmp/foo"])

  def testAllowed(self):
    filestorage._CheckFileStoragePath("/tmp/foo/a", ["/tmp/foo"])
    filestorage._CheckFileStoragePath("/tmp/foo/a/x", ["/tmp/foo"])


class TestCheckFileStoragePathExistance(testutils.GanetiTestCase):
  def testNonExistantFile(self):
    filename = "/tmp/this/file/does/not/exist"
    assert not os.path.exists(filename)
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance, "/bin/",
                      _filename=filename)
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/srv/file-storage", _filename=filename)

  def testAllowedPath(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      /srv/storage
      """)

    filestorage.CheckFileStoragePathAcceptance(
        "/srv/storage/inst1", _filename=tmpfile)

    # No additional path component
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/srv/storage", _filename=tmpfile)

    # Forbidden path
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/usr/lib64/xyz", _filename=tmpfile)


class TestGlusterVolume(unittest.TestCase):

  last_vol_name = 0

  @classmethod
  def makeVolume(cls, ipv = 4, addr=None, port = 9001,
                 run_cmd = NotImplemented,
                 clone_previous=False,
                 name=None):

    address = {4: "74.65.28.66",
               6: "74:65::28:6:69",
              } # T9

    vol_name = TestGlusterVolume.last_vol_name
    if name:
      vol_name = name
    else:
      try:
        vol_name = int(vol_name)
        vol_name += 1 if not clone_previous else 0
      except:
        vol_name = 0 if not clone_previous else vol_name

    return filestorage.GlusterVolume(address[ipv] if not addr else addr,
                                     port,
                                     str(vol_name),
                                     _run_cmd=run_cmd
                                    )

    TestGlusterVolume.last_vol_name = vol_name

  def setUp(self):
    self.result_failed = utils.RunResult(1, None, "", "", "", None, None)
    self.mock_okay_run_cmd = mock.Mock(return_value=RESULT_OK)
    self.result_ok = utils.RunResult(0, None, "", "", "", None, None)
    self.mock_fail_run_cmd = mock.Mock(return_value=RESULT_FAILED)

    # Create some volumes.
    self.vol_a = TestGlusterVolume.makeVolume()
    self.vol_a_clone = TestGlusterVolume.makeVolume(clone_previous = True)
    self.vol_b = TestGlusterVolume.makeVolume()

  def TestEquality(self):
    self.assertEqual(self.vol_a, self.vol_a_clone)

  def TestInequality(self):
    self.assertNotEqual(self.vol_a, self.vol_b)

  def TestDictionary(self):
    dictionary = {}
    dictionary[self.vol_a] = "pink bunny"
    self.assertEqual("pink_bunny", dictionary.get(self.vol_a_clone, "Error"))
    self.assertRaises(KeyError, lambda: dictionary[self.vol_b])

  def TestHostnameResolution(self):
    vol_1 = makeVolume(addr="localhost")
    self.assertEqual(vol_1.server_ip, "127.0.0.1")
    self.assertRaises(errors.ResolverError, lambda: makeVolume(addr="E_NOENT"))

  def TestKVMGlusterFSURIs(self):
    # The only source of documentation I can find is:
    #   https://github.com/qemu/qemu/commit/8d6d89c
    # This test gets as close as possible to the examples given there,
    # within the limits of our implementation (no transport specification,
    #                                          no default port version).

    vol_1 = makeVolume(addr="1.2.3.4", port=24007, name="testvol")
    self.assertEqual(vol_1.GetKVMMountString("dir/a.img"),
                     "gluster://1.2.3.4:24007/testvol/dir/a.img")

    vol_2 = makeVolume(addr="1:2:3:4:5:6:7:8", port=24007, name="testvol")
    self.assertEqual(vol_1.GetKVMMountString("dir/a.img"),
                     "gluster://[1:2:3:4:5:6:7:8]:24007/testvol/dir/a.img")

    # Technically KVM could do name resolution on its own, but we don't do that
    # for mount point deduplication purposes.
    vol_3 = makeVolume(addr="localhost", port=24007, name="testvol")
    self.assertEqual(vol_1.GetKVMMountString("dir/a.img"),
                     "gluster://127.0.0.1:24007/testvol/dir/a.img")

  def TestPathAcceptance(self):
    #Simply check no exceptions are raised.
    filestorage.CheckFileStoragePathAcceptance(vol_1.mount_point)

if __name__ == "__main__":
  testutils.GanetiTestProgram()
