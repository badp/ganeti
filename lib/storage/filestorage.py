#
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


"""Disk-based disk templates and functions.

"""

import logging
import errno
import os

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import pathutils
from ganeti import utils
from ganeti.storage import base


class FileDeviceHelper(object):
  def __init__(self, path, disk_template,
               create_with_size=None, create_folder=False):
    """Create a new file.

    @param create_with_size: do not attempt to open an existing file; instead
                             create one and truncate it to this size (in MiB)
    @raise errors.FileStoragePathError: if the file path is disallowed by policy
    """

    CheckFileStoragePathAcceptance(path, disk_template)

    self.path = path
    if create_folder:
      folder = os.path.dirname(path)
      io.Makedirs(folder)

    if create_with_size:
      try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
        f = os.fdopen(fd, "w")
        f.truncate(create_with_size * 1024 * 1024)
        f.close()
      except EnvironmentError as err:
        base.ThrowError("%s: can't create: %s", path, str(err))

  def Exists(self, assert_exists=None):
    """Check for the existence of the given file.

    @param assert_exists: creates an assertion on the result value
      * if true, raise IOError if the file does not exist
      * if false, raise IOError if the file does exist
    @rtype: boolean
    @return: True if the file exists
    """

    exists = os.path.exists(self.path)

    if not exists and assert_exists is True:
      raise IOError(2, "No such file or directory", self.path)
    if exists and assert_exists is False:
      raise IOError(17, "File exists", self.path)

    return exists

  def Remove(self):
    """Remove the file backing the block device.

    @rtype: boolean
    @return: True if the removal was successful

    """
    try:
      os.remove(self.path)
    except OSError as err:
      if err.errno != errno.ENOENT:
        base.ThrowError("%s: can't remove: %s", self.path, err)

  def Size(self):
    """Return the actual disk size in bytes.

    @return: The file size in bytes.
    """
    try:
      return os.stat(self.path).st_size
    except OSError as err:
      base.ThrowError("%s: can't stat: %s", self.path, err)

  def Grow(self, amount):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow by.
    """
    # Check that the file exists
    self.Exists(assert_exists=True)
    current_size = self.Size()
    if amount < 0:
      base.ThrowError("%s: can't grow by negative amount", self.path, amount)
    new_size = current_size + amount * 1024 * 1024
    try:
      f = open(self.path, "a+")
      f.truncate(new_size)
      f.close()
    except EnvironmentError, err:
      base.ThrowError("%s: can't grow: ", self.path, str(err))


class FileStorage(base.BlockDev):
  """File device.

  This class represents a file storage backend device.

  The unique_id for the file device is a (file_driver, file_path) tuple.

  @todo: FileDeviceHelper has no way to know if it is servicing a DT_FILE or
         DT_SHARED_FILE disk template. For now this doesn't matter (this
         information is only used for storage path validation, and that
         component also doesn't distinguish between the two), but this could be
         an area for slight improvement in the future.
  """
  def __init__(self, unique_id, children, size, params, dyn_params,
               _file_helper_obj=None):
    """Initalizes a file device backend.

    """
    if children:
      raise errors.BlockDeviceError("Invalid setup for file device")
    super(FileStorage, self).__init__(unique_id, children, size, params,
                                      dyn_params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self.driver = unique_id[0]
    self.dev_path = unique_id[1]

    if not _file_helper_obj:
      self.file = FileDeviceHelper(self.dev_path,
                                   constants.DT_FILE) # see todo above.
    else:
      self.file = _file_helper_obj
      if self.dev_path != self.file.path:
        raise errors.ProgrammerError("FileStorage.__init__ called with bad"
                                     " prebuilt FileDeviceHelper object:"
                                     " costructor got '%s', "
                                     " helper says '%s'." % (self.dev_path,
                                                             self.file.path))

    self.Attach()

  def Assemble(self):
    """Assemble the device.

    Checks whether the file device exists, raises BlockDeviceError otherwise.

    """
    self.file.Exists(assert_exists=True)

  def Shutdown(self):
    """Shutdown the device.

    This is a no-op for the file type, as we don't deactivate
    the file on shutdown.

    """
    pass

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the file type.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the file type.

    """
    pass

  def Remove(self):
    """Remove the file backing the block device.

    @rtype: boolean
    @return: True if the removal was successful

    """
    self.file.Remove()
    return True

  def Rename(self, new_id):
    """Renames the file.

    """
    # TODO: implement rename for file-based storage
    base.ThrowError("Rename is not supported for file-based storage")

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow with

    """
    if not backingstore:
      return
    if dryrun:
      return
    self.file.Grow(amount)

  def Attach(self):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    self.attached = self.file.Exists()
    return self.attached

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    return self.file.Size()

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params):
    """Create a new file.

    @param size: the size of file in MiB

    @rtype: L{bdev.FileStorage}
    @return: an instance of FileStorage

    """
    if excl_stor:
      raise errors.ProgrammerError("FileStorage device requested with"
                                   " exclusive_storage")
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    dev_path = unique_id[1]

    file_helper = FileDeviceHelper(dev_path, constants.DT_FILE,
                                   create_with_size=size)
    return FileStorage(unique_id, children, size, params, dyn_params,
                       _file_helper_obj=file_helper)


def GetFileStorageSpaceInfo(path):
  """Retrieves the free and total space of the device where the file is
     located.

     @type path: string
     @param path: Path of the file whose embracing device's capacity is
       reported.
     @return: a dictionary containing 'vg_size' and 'vg_free' given in MebiBytes

  """
  try:
    result = os.statvfs(path)
    free = (result.f_frsize * result.f_bavail) / (1024 * 1024)
    size = (result.f_frsize * result.f_blocks) / (1024 * 1024)
    return {"type": constants.ST_FILE,
            "name": path,
            "storage_size": size,
            "storage_free": free}
  except OSError, e:
    raise errors.CommandError("Failed to retrieve file system information about"
                              " path: %s - %s" % (path, e.strerror))


def _GetForbiddenFileStoragePaths():
  """Builds a list of path prefixes which shouldn't be used for file storage.

  @rtype: frozenset

  """
  paths = set([
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/proc",
    "/root",
    "/sys",
    ])

  for prefix in ["", "/usr", "/usr/local"]:
    paths.update(map(lambda s: "%s/%s" % (prefix, s),
                     ["bin", "lib", "lib32", "lib64", "sbin"]))

  return compat.UniqueFrozenset(map(os.path.normpath, paths))


def _ComputeWrongFileStoragePaths(paths,
                                  _forbidden=_GetForbiddenFileStoragePaths()):
  """Cross-checks a list of paths for prefixes considered bad.

  Some paths, e.g. "/bin", should not be used for file storage.

  @type paths: list
  @param paths: List of paths to be checked
  @rtype: list
  @return: Sorted list of paths for which the user should be warned

  """
  def _Check(path):
    return (not os.path.isabs(path) or
            path in _forbidden or
            filter(lambda p: utils.IsBelowDir(p, path), _forbidden))

  return utils.NiceSort(filter(_Check, map(os.path.normpath, paths)))


def ComputeWrongFileStoragePaths(_filename=pathutils.FILE_STORAGE_PATHS_FILE):
  """Returns a list of file storage paths whose prefix is considered bad.

  See L{_ComputeWrongFileStoragePaths}.

  """
  return _ComputeWrongFileStoragePaths(_LoadAllowedFileStoragePaths(_filename))


def _CheckFileStoragePath(path, allowed, exact_match_ok=False):
  """Checks if a path is in a list of allowed paths for file storage.

  @type path: string
  @param path: Path to check
  @type allowed: list
  @param allowed: List of allowed paths
  @type exact_match_ok: bool
  @param exact_match_ok: whether or not it is okay when the path is exactly
      equal to an allowed path and not a subdir of it
  @raise errors.FileStoragePathError: If the path is not allowed

  """
  if not os.path.isabs(path):
    raise errors.FileStoragePathError("File storage path must be absolute,"
                                      " got '%s'" % path)

  for i in allowed:
    if not os.path.isabs(i):
      logging.info("Ignoring relative path '%s' for file storage", i)
      continue

    if exact_match_ok:
      if os.path.normpath(i) == os.path.normpath(path):
        break

    if utils.IsBelowDir(i, path):
      break
  else:
    raise errors.FileStoragePathError("Path '%s' is not acceptable for file"
                                      " storage" % path)


def _LoadAllowedFileStoragePaths(filename):
  """Loads file containing allowed file storage paths.

  @rtype: list
  @return: List of allowed paths (can be an empty list)

  """
  try:
    contents = utils.ReadFile(filename)
  except EnvironmentError:
    return []
  else:
    return utils.FilterEmptyLinesAndComments(contents)


def CheckFileStoragePathAcceptance(path,
                                   disk_templates=None,
                                   _filename=pathutils.FILE_STORAGE_PATHS_FILE,
                                   exact_match_ok=False):
  """Checks if a path is allowed for file storage.

  @type path: string
  @param path: Path to check
  @raise errors.FileStoragePathError: If the path is not allowed
  @type disk_templates: a string or list of strings from DTS_FILEBASED
  @param disk_templates: disk template(s) for which path must be valid. If
                         multiple templates are given, then it is sufficient for
                         path to be valid for any of the specified disk
                         templates for the check to pass.

  """
  if disk_templates is None:
    disk_templates = constants.DTS_FILEBASED

  if not isinstance(disk_templates, list):
    disk_templates = [disk_templates]

  bad_templates = filter(lambda t: t not in constants.DTS_FILEBASED,
                         disk_templates)

  if bad_templates:
    raise errors.ProgrammerError("Invalid templates %s for path checking")

  allowed = []
  if (constants.DT_FILE in disk_templates or
      constants.DT_SHARED_FILE in disk_templates):
    allowed = _LoadAllowedFileStoragePaths(_filename)

  if constants.DT_GLUSTER in disk_templates:
    allowed.append(constants.GLUSTER_MOUNTPOINT)

  if not allowed:
    raise errors.FileStoragePathError("No paths are valid or path file '%s'"
                                      " is not accessible." % _filename)
  if _ComputeWrongFileStoragePaths([path]):
    raise errors.FileStoragePathError("Path '%s' uses a forbidden prefix" %
                                      path)

  _CheckFileStoragePath(path, allowed, exact_match_ok=exact_match_ok)


def _CheckFileStoragePathExistance(path):
  """Checks whether the given path is usable on the file system.

  This checks wether the path is existing, a directory and writable.

  @type path: string
  @param path: path to check

  """
  if not os.path.isdir(path):
    raise errors.FileStoragePathError("Path '%s' is not existing or not a"
                                      " directory." % path)
  if not os.access(path, os.W_OK):
    raise errors.FileStoragePathError("Path '%s' is not writable" % path)


def CheckFileStoragePath(
      path, disk_templates=None,
      _allowed_paths_file=pathutils.FILE_STORAGE_PATHS_FILE
    ):
  """Checks whether the path exists and is acceptable to use.

  Can be used for any file-based storage, for example shared-file storage.

  @type path: string
  @param path: path to check
  @type disk_templates: a string or list of strings from DTS_FILEBASED
  @param disk_templates: disk template(s) for which path must be valid. If
                        multiple templates are given, then it is sufficient for
                        path to be valid for any of the specified disk templates
                        for the check to pass.
  @rtype: string
  @returns: error message if the path is not ready to use

  """
  try:
    CheckFileStoragePathAcceptance(path,
                                   disk_templates,
                                   _filename=_allowed_paths_file,
                                   exact_match_ok=True)
  except errors.FileStoragePathError as e:
    return str(e)
  if not os.path.isdir(path):
    return "Path '%s' is not exisiting or not a directory." % path
  if not os.access(path, os.W_OK):
    return "Path '%s' is not writable" % path
