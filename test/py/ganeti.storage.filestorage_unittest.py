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


"""Script for unittesting the ganeti.storage.filestorage module"""

import os
import shutil
import tempfile
import unittest

from ganeti import errors
from ganeti.storage import filestorage
from ganeti.utils import io
from ganeti import utils
from ganeti import constants

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
        path, constants.DT_FILE,
        _allowed_paths_file=self.allowed_paths_filename)
    self.assertEqual(None, result)

  def testCheckFileStoragePathNotAllowed(self):
    path = os.path.join(self.tmpdir, "notallowed")
    result = filestorage.CheckFileStoragePath(
        path, constants.DT_FILE,
        _allowed_paths_file=self.allowed_paths_filename)
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
    for disk_template in constants.DTS_FILEBASED:
      self.assertRaises(errors.FileStoragePathError,
                        filestorage.CheckFileStoragePathAcceptance,
                        "/bin/",
                        disk_template,
                        _filename=filename)
      self.assertRaises(errors.FileStoragePathError,
                        filestorage.CheckFileStoragePathAcceptance,
                        "/srv/file-storage",
                        disk_template,
                        _filename=filename)

  def testAllowedPath(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      /srv/storage
      """)

    okay_path = {
      constants.DT_FILE: "/srv/storage/inst1",
      constants.DT_SHARED_FILE: "/srv/storage/inst2",
      constants.DT_GLUSTER: utils.io.PathJoin(constants.GLUSTER_MOUNTPOINT,
                                              "inst1"),
    }

    bad_path = {
      constants.DT_FILE: "/srv/storage",
      constants.DT_SHARED_FILE: "/srv/storage",
      constants.DT_GLUSTER: constants.GLUSTER_MOUNTPOINT,
    }

    forbidden_path = {
      constants.DT_FILE: "/usr/lib64/xyz",
      constants.DT_SHARED_FILE: "/bin/xyz",
      constants.DT_GLUSTER: "/sys/xyz",
    }

    # Check invalid disk template.
    self.assertRaises(errors.ProgrammerError, lambda:
      filestorage.CheckFileStoragePathAcceptance("foo", constants.DT_RBD))

    for dt in constants.DTS_FILEBASED:
      try:
        filestorage.CheckFileStoragePathAcceptance(okay_path[dt],
                                                   dt,
                                                   _filename=tmpfile)
      except errors.FileStoragePathError:
        self.fail("%r rejected for %r" % (okay_path[dt],
                                          dt))

      # No additional path component
      try:
        filestorage.CheckFileStoragePathAcceptance(bad_path[dt],
                                                   dt,
                                                   _filename=tmpfile)
        self.fail("%r not rejected for %r" % (bad_path[dt],
                                              dt))
      except errors.FileStoragePathError:
        pass

      # Forbidden path
      try:
        filestorage.CheckFileStoragePathAcceptance(forbidden_path[dt],
                                                   dt,
                                                   _filename=tmpfile)
        self.fail("%r not rejected for %r" % (forbidden_path[dt],
                                              dt))
      except errors.FileStoragePathError:
        pass

class TestFileDeviceHelper(testutils.GanetiTestCase):
  def test(self):
    # Get temp directory
    directory = tempfile.mkdtemp()
    subdirectory = io.PathJoin(directory, "pinky")
    path = io.PathJoin(subdirectory, "bunny")
    constructor = lambda path: \
      filestorage.FileDeviceHelper(
        path,
        _skip_file_storage_acceptance_check_for_testing_purposes=True
      )

    should_fail = lambda fn: self.assertRaises(errors.BlockDeviceError, fn)

    # Make sure it doesn't exist, and methods check for it
    constructor(path, dt_test).Exists(assert_exists=False)
    should_fail( lambda: \
      constructor(path, dt_test).Exists(assert_exists=True))
    should_fail( lambda: \
      constructor(path, dt_test).Size())
    should_fail( lambda: \
      constructor(path, dt_test).Grow(20))

    # Removing however fails silently.
    constructor(path, dt_test).Remove()

    # Make sure we don't create all directories for you unless we ask for it
    should_fail( lambda: \
      constructor(path, dt_test, create_with_size=42))

    # Create the file.
    fileHelper = constructor(path, dt_test,
                             create_with_size=42,
                             create_folder=True)

    # This should still fail.
    should_fail( lambda: \
      constructor(subdirectory, dt_test).Size())


    self.assertTrue(fileHelper.Exists())

    should_fail( lambda: \
      constructor(path, dt_test, create_with_size=42))

    fileHelper.Exists(assert_exists=True)
    should_fail( lambda: \
      constructor(path, dt_test).Exists(assert_exists=False))

    should_fail( lambda: \
      constructor(path, dt_test).Grow(-30))

    fileHelper.Grow(58)
    self.assertEqual(100 * 1024 * 1024, fileHelper.Size())

    fileHelper.Remove()
    fileHelper.Exists(assert_exists=False)

    os.rmdir(subdirectory)
    os.rmdir(directory)

if __name__ == "__main__":
  testutils.GanetiTestProgram()
