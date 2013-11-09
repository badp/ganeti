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
import os
import socket

from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import constants
from ganeti.hypervisor import hv_kvm

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

  def __init__(self, server_addr, port, volume, _run_cmd=utils.RunCmd):
    self.server_addr = server_addr
    server_ip = netutils.Hostname.GetIP(self.server_addr)
    self._server_ip = server_ip
    port = netutils.ValidatePortNumber(port)
    self._port = port
    self._volume = volume
    self.mount_point = io.PathJoin(constants.GLUSTER_MOUNTPOINT,
                                   self._volume)

    self._run_cmd = _run_cmd

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

  def _IsActuallyMounted(self):

    if not os.path.exists(self.mount_point):
      return False

    with file("/etc/mtab") as fobj:
      data = fobj.readlines()

    before = [item.split(" ")[0:3] for item in data]
    filtered = [item[0:2] for item in before if item[2] == "fuse.glusterfs"]

    for server, mount_point in filtered:
      if os.path.samefile(mount_point, self.mount_point) and \
         server == self._GetMtabString():
        return True

    return False

  def _GuessMountFailReasons(self):
    reasons = []

    # Does the mount point exist?
    if not os.path.exists(self.mount_point):
      reasons.append("%r: does not exist" % self.mount_point)

    # Okay, it exists, but is it a directory?
    elif not os.path.isdir(self.mount_point):
      reasons.append("%r: not a directory" % self.mount_point)

    # If, for some unfortunate reason, this folder exists before mounting:
    #
    #   /var/run/ganeti/gluster/gv0/10.0.0.1:30000:gv0/
    #   '--------- cwd ------------'
    #
    # and you _are_ trying to mount the gluster volume gv0 on 10.0.0.1:30000,
    # then the mount.glusterfs command parser gets confused and this command:
    #
    #   mount -t glusterfs 10.0.0.1:30000:gv0 /var/run/ganeti/gluster/gv0
    #                      '-- remote end --' '------ mountpoint -------'
    #
    # gets parsed instead like this:
    #
    #   mount -t glusterfs 10.0.0.1:30000:gv0 /var/run/ganeti/gluster/gv0
    #                      '-- mountpoint --' '----- syntax error ------'
    #
    # and if there _is_ a gluster server running locally at the default remote
    # end, localhost:24007, then this is not a network error and therefore... no
    # usage message gets printed out. All you get is a Byson parser error in the
    # gluster log files about an unexpected token in line 1, "". (That's stdin.)
    #
    # Not that we rely on that output in any way whatsoever...

    parser_confusing = io.PathJoin(self.mount_point,
                                   self._GetFUSEMountString())
    if os.path.exists(parser_confusing):
      reasons.append("%r: please delete, rename or move." % parser_confusing)

    # Let's try something else: can we connect to the server?
    conn_failed = False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      sock.connect((self.server_ip, self.port))
      sock.close()
    except socket.error as err:
      reasons.append("%s:%d: %s" % (self.server_ip, self.port, err.strerror))
      conn_failed = True

    # Okay, we _could_ connect. But does the volume exist?
    if not conn_failed:
      # It's hard to tell unless Gluster is installed, which is not a guarantee.
      try:
        result = self._run_cmd([
          "gluster",
          # yay, undocumented switches! This option added at git revision
          # d787bca4 in 2010 so it _should_ be safe to use?
          "--remote-host=%s" % self.server_ip, # There is no switch for port...
          "volume", "info", self.volume
        ])

        # Okay, we have it!
        if result.failed:
          reasons.append("gluster: %s: %s" % (result.fail_reason,
                                              result.output.rstrip()))
        else:
          message = result.output.splitlines()
          if not "Status: Started" in message:
            reasons.append("volume %s: not started" % self.volume)
          if not "Transport-type: tcp" in message:
            reasons.append("volume %s: unsupported transport" % self.volume)

      except errors.OpExecError as err:
        # Gluster is not installed. What do?
        reasons.append("try running 'gluster volume info %s' on %s to ensure"
                       " it exists, it is started and it is using the tcp"
                       " transport" % (self.volume, self.server_ip))

    return "; ".join(reasons)

  def _GetFUSEMountString(self):
    return "{ip}:{port}:{volume}" \
             .format(ip=self.server_ip, port=self.port, volume=self.volume)

  def GetKVMMountString(self, path):
    ip = self.server_ip
    if ":" in self.server_ip: # IPv6 addresses need []-quoting
      ip = "[%s]" % ip
    return "gluster://{ip}:{port}/{volume}/{path}" \
             .format(ip=ip, port=self.port, volume=self.volume, path=path)

  def _GetMtabString(self):
    return "{ip}:{volume}" \
             .format(ip=self.server_ip, port=self.port, volume=self.volume)

  def Mount(self):
    if os.path.isdir(self.mount_point) and \
       not os.path.ismount(self.mount_point):
      logging.warning("%r: already exists as a regular directory",
                      self.mount_point)

    if self._IsActuallyMounted():
      return

    command = ["mount",
               "-t", "glusterfs",
               self._GetFUSEMountString(),
               self.mount_point
              ]

    io.Makedirs(self.mount_point)
    self._run_cmd(" ".join(command),
                  # Why set cwd? Because it's an area we control. If,
                  # for some unfortunate reason, this folder exists:
                  #   "/%s/" % _GetFUSEMountString()
                  # ...then the gluster parser gets confused and treats
                  # _GetFUSEMountString() as your mount point and
                  # self.mount_point becomes a syntax error.
                  cwd=self.mount_point)

    # mount.glusterfs exits with code 0 even after failure.
    # https://bugzilla.redhat.com/show_bug.cgi?id=1031973
    if not self._IsActuallyMounted():
      reasons = self._GuessMountFailReasons()
      if not reasons:
        reasons = "%r failed." % (" ".join(command))
      base.ThrowError("%r: mount failure: %s",
                      self.mount_point,
                      reasons)

  def Unmount(self):
    if not self._IsActuallyMounted():
      base.ThrowError("%r should be mounted but isn't.", self.mount_point)

    result = self._run_cmd(["umount",
                            self.mount_point])

    if result.failed:
      logging.warning("Failed to unmount %r from %r: %s",
                      self, self.mount_point, result.fail_reason)

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
      driver, path = unique_id
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
    self.full_path = io.PathJoin(self.volume.mount_point, self.path)
    self.file = None if not _file_helper_obj else _file_helper_obj

    super(GlusterStorage, self).__init__(unique_id, children, size,
                                         params, dyn_params)

    self.Attach()

  def Assemble(self):
    """Assemble the device.

    Checks whether the file device exists, raises BlockDeviceError otherwise.

    """
    assert self.attached, "Gluster file assembled without being attached"
    self.file.Exists(assert_exists=True)

  def Shutdown(self):
    """Shutdown the device.

    """

    del self.file
    self.file = None
    self.dev_path = None
    self.attached = False
    self.volume.Unmount()

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the file type.

    """
    assert self.attached, "Gluster file opened without being attached"

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
    with self.volume:
      self.file = FileDeviceHelper(self.full_path, constants.DT_GLUSTER)
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
    if dryrun:
      return
    self.file.Grow(amount)

  def Attach(self):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    try:
      self.volume.Mount()
      self.file = FileDeviceHelper(self.full_path, constants.DT_GLUSTER)
      self.dev_path = self.full_path
    except Exception as err:
      self.volume.Unmount()
      raise err

    self.attached = True
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

    full_path = unique_id[1]

    server_addr = params[constants.GLUSTER_HOST]
    port = params[constants.GLUSTER_PORT]
    volume = params[constants.GLUSTER_VOLUME]

    volume_obj = GlusterVolume(server_addr, port, volume)
    full_path = io.PathJoin(volume_obj.mount_point, full_path)

    # Possible optimization: defer actual creation to first Attach, rather
    # than mounting and unmounting here, then remounting immediately after.
    with volume_obj:
      file_helper_obj = FileDeviceHelper(full_path,
                                         constants.DT_GLUSTER,
                                         create_with_size=size,
                                         create_folder=True)

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
