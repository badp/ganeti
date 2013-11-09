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

"""Gluster storage class.

This class is very similar to FileStorage, given that Gluster when mounted
behaves essentially like a regular file system. Unlike RBD, there are no
special provisions for block device abstractions (yet).

"""
import logging

from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import constants

from ganeti.utils import io
from ganeti.storage import base
from ganeti.storage.filestorage import FileDeviceHelper


class GlusterVolume(object):
  """This class represents a Gluster volume.

  Volumes are uniquely identified by:

    - their IP address
    - their port
    - the volume name itself

  Two GlusterVolume objects x, y with same IP address, port and volume name
  are considered equal. connection_count makes sure that mounts and unmounts to
  equal volumes are not made multiple times.
  """

  connection_count = {}
  """Tracks how many drives are being used on the same Gluster volume.
  """ # pylint: disable=W0105

  def __init__(self, server_addr, port, volume, _run_cmd=utils.RunCmd):
    self.server_addr = server_addr
    server_ip = netutils.Hostname.GetIP(self.server_addr)
    self._server_ip = server_ip
    port = netutils.ValidatePortNumber(port)
    self._port = port
    self._volume = volume
    self.mount_point = constants.GLUSTER_MOUNTPOINT

    self._run_cmd = _run_cmd

    self._mounted = False
    """self._mounted is True is self counts towards a volume's connection count.

    """ # pylint: disable=W0105

  # This object is hashable and has custom equality, so we must do a little
  # extra work to guarantee the immutability of its core parts.

  @property
  def server_ip(self):
    return self._server_ip

  @property
  def port(self):
    return self._port

  @property
  def volume(self):
    return self._volume

  def __eq__(self, other):
    # The hash has full knowledge of the important bits, so let's use it.
    return self.__hash__() == other.__hash__()

  def __repr__(self):
    # This is used by __hash__ and __eq__, be careful.
    # Two GlusterVolumes with the same __repr__ are considered the same
    # for connection_count purposes.
    return """GlusterVolume("{ip}", {port}, "{volume}")""" \
             .format(ip=self.server_ip, port=self.port, volume=self.volume)

  def __hash__(self):
    return self.__repr__().__hash__()

  def _GetFUSEMountString(self):
    return "{ip}:{port}:{volume}" \
             .format(ip=self.server_ip, port=self.port, volume=self.volume)

  def GetKVMMountString(self, path):
    ip = self.server_ip
    if ":" in self.server_ip: # IPv6 addresses need []-quoting
      ip = "[%s]" % ip
    return "gluster://{ip}:{port}/{volume}/{path}" \
             .format(ip=ip, port=self.port, volume=self.volume, path=path)

  def Mount(self):
    if self._mounted:
      return
    count = GlusterVolume.connection_count.get(self, 0)
    if count > 0:
      pass # We're already mounted!
    else:
      # Make the folder if necessary.
      io.Makedirs(self.mount_point)
      result = self._run_cmd(["mount",
                              "-t", "glusterfs",
                              self._GetFUSEMountString(),
                              self.mount_point
                             ])
      if result.failed:
        raise errors.BlockDeviceError(
          "Failed to mount %s on %s: %s" % (repr(self),
                                            self.mount_point,
                                            result.fail_reason)
        )
    self._mounted = True
    GlusterVolume.connection_count[self] = count + 1

  def Unmount(self):
    if not self._mounted:
      return
    count = GlusterVolume.connection_count[self] - 1
    if count > 0:
      pass # Other volumes are still using this connection.
    else:
      result = self._run_cmd(["umount", self.mount_point])
      if result.failed: # Not awesome, but not a show-stopper either.
        logging.warning("Failed to unmount %s: %s",
                        repr(self), result.fail_reason)
        return # do not update _mounted and connection_count
    self._mounted = False
    GlusterVolume.connection_count[self] = count

  def __enter__(self):
    self.Mount()
    return self

  def __exit__(self, *exception_information):
    self.Unmount()


class GlusterStorage(base.BlockDev):
  """File device.

  This class represents a file storage backend device stored on Gluster. Ganeti
  mounts and unmounts the Gluster devices automatically.

  The unique_id for the file device is a (file_driver, file_path) tuple.

  """
  def __init__(self, unique_id, children, size, params, dyn_params,
               _file_helper_obj=None, _volume_obj=None):
    """Initalizes a file device backend.

    """
    if children:
      raise errors.BlockDeviceError("Invalid setup for file device")

    try:
      path, driver = unique_id
    except ValueError: # wrong number of arguments
      raise ValueError("Invalid configuration data %s" % repr(unique_id))

    server_addr = params[constants.GLUSTER_HOST]
    port = params[constants.GLUSTER_PORT]
    volume = params[constants.GLUSTER_VOLUME]

    if _volume_obj:
      self.volume = _volume_obj
    else:
      self.volume = GlusterVolume(server_addr, port, volume)
    self.path = path
    self.driver = driver
    self.dev_path = io.PathJoin(self.volume.mount_point, self.path[:1])
    self.file = None if not _file_helper_obj else _file_helper_obj

    super(GlusterStorage).__init__(unique_id, children, size,
                                   params, dyn_params)

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
    del self.file
    self.file = None
    self.volume.Unmount()

  def Remove(self):
    """Remove the file backing the block device.

    @rtype: boolean
    @return: True if the removal was successful

    """
    self.file.Remove()
    self.file = None
    return True

  def Rename(self, new_id):
    """Renames the file.

    """
    # TODO: implement rename for file-based storage
    base.ThrowError("Rename is not supported for Gluster storage")

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow with

    """
    if not backingstore:
      return
    self.file.Grow(amount)

  def Attach(self):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    self.volume.Mount()
    self.file = FileDeviceHelper()
    return self.file.Exists()

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

    server_addr = params[constants.GLUSTER_HOST]
    port = params[constants.GLUSTER_PORT]
    volume = params[constants.GLUSTER_VOLUME]

    volume_obj = GlusterVolume(server_addr, port, volume)
    dev_path = io.PathJoin(volume_obj.mount_point, dev_path[1:])

    # Possible optimization: defer actual creation to first Attach, rather
    # than mounting and unmounting here, then remounting immediately after.
    with volume_obj:
      file_helper_obj = FileDeviceHelper(dev_path, create_with_size=size)

    return GlusterStorage(unique_id, children, size, params, dyn_params,
                          _volume_obj=volume_obj,
                          _file_helper_obj=file_helper_obj)

  def GetUserspaceAccessUri(self, hypervisor):
    """Generate KVM userspace URIs to be used as `-drive file` settings.

    @see: L{BlockDev.GetUserspaceAccessUri}
    @see: https://github.com/qemu/qemu/commit/8d6d89cb63c57569864ecdeb84d3a1c2eb
    """
    if hypervisor == constants.HT_KVM:
      return self.volume.GetKVMMountString(self.path)
    else:
      base.ThrowError("Hypervisor %s doesn't support Gluster userspace access" %
                      hypervisor)
