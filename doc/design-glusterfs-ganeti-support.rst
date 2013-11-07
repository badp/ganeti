========================
GlusterFS Ganeti support
========================

This document describes the plan for adding GlusterFS support inside Ganeti.

.. contents:: :depth: 4
.. highlight:: shell-example

Objective
=========

The aim is to let Ganeti support GlusterFS as one of its backend storage.
This includes three aspects to finish:

- Add Gluster as a storage backend.
- Make sure Ganeti VMs can use GlusterFS backends in userspace mode (for
  newer QEMU/KVM which has this support) and otherwise, if possible, through
  some kernel exported block device.
- Make sure Ganeti can configure GlusterFS by itself, by just joining
  storage space on new nodes to a GlusterFS nodes pool. Note that this
  may need another design document that explains how it interacts with
  storage pools, and that the node might or might not host VMs as well.

Background
==========

There are two possible ways to implement "GlusterFS Ganeti Support". One is
GlusterFS as one of external backend storage, the other one is realizing
GlusterFS inside Ganeti, that is, as a new disk type for Ganeti. The benefit
of the latter one is that it would not be opaque but fully supported and
integrated in Ganeti, which would not need to add infrastructures for
testing/QAing and such. Having it internal we can also provide a monitoring
agent for it and more visibility into what's going on. For these reasons,
GlusterFS support will be added directly inside Ganeti.

Gluster support in Ganeti
=========================

Working with GlusterFS in kernel space essentially boils down to two steps:

1. Mount the Gluster volume.
2. Use files stored in the volume as instance disks.

In other words, Gluster storage is a shared file storage backend, essentially.
Ganeti just needs to mount and unmount the Gluster volume(s) appropriately
before and after operation.

Since it is not strictly necessary for Gluster to mount the disk if all that's
needed is userspace access, however, it is inappropriate for the Gluster storage
class to inherit from FileStorage. So we should resort to composition rather
than inheritance:

- Extract the FileStorage behavior into a FileDeviceHelper class.
- Use the FileDeviceHelper class to implement a GlusterStorage class

In order not to further inflate bdev.py, we should move FileStorage together
with its helper function (thus reducing their visibility) and add Gluster to its
own file, gluster.py. Moving the other classes to their own files (like it's
been done in lib/hypervisor/) is probably outside the scope of a patch series
that simply aims to implement Gluster.

Changes to the storage types system
===================================

Ganeti has a number of storage types that abstract over disk templates. This
matters mainly in terms of disk space reporting. Gluster support is improved by
a rethinking of how disk templates are assigned to storage types in Ganeti.

+--------------+---------+--------------+-------------------------------------+
|Disk template | Before  | After        | Characteristics                     |
+==============+=========+==============+=====================================+
| File         | File    | File storage | - ``gnt-node list`` enabled         |
|              | storage | type         | - ``gnt-node list-storage`` enabled |
|              | type    |              | - ``hail`` uses disk information    |
+--------------+         +--------------+-------------------------------------+
| Shared file  |         | Shared file  | - ``gnt-node`` list disabled        |
+--------------+---------+ storage type | - ``gnt-node`` list-storage enabled |
| Gluster (new)| N/A     | (new)        | - ``hail`` ignores disk information |
+--------------+---------+--------------+-------------------------------------+

The rationale is simple. For shared file and gluster storage, disk space is not
a function of any one node. If storage types with disk space reporting are used,
Hail expects them to give useful numbers for allocation purposes, but a shared
storage system means disk balancing is not affected by node-instance allocation
any longer. Moreover, it would be wasteful to mount a Gluster volume on each
node just for running statvfs() if no machine was actually running gluster
VMs.

As a result, Gluster support for gnt-node list-storage is necessarily limited
and nodes on which Gluster is available but not in use will report failures.
Additionally, running gnt-node list will give an output like this::

  Node              DTotal DFree MTotal MNode MFree Pinst Sinst
  node1.example.com      ?     ?   744M  273M  477M     0     0
  node2.example.com      ?     ?   744M  273M  477M     0     0

This is expected and consistent with behaviour in RBD. A future improvement may
involve not displaying those columns at all in the command output unless
per-node disk resources are actually in use.

Gluster deployment by Ganeti
============================

Basic GlusterFS deployment is relatively simple:

1. Create bricks on nodes 1..n
2. Mount them to /export/brick1/gluster
3. On nodes 2..n, run `gluster peer probe`
4. On node 1, run `gluster volume create`, enumerating all bricks.
5. On node 1, run `gluster volume start`

From here onwards, however, the sky's the limit. Gluster has support for
translators, essentially "pure transformations" of simpler volumes. The
`distribute` translator, for example, takes arbitrary "subvolumes" and
distributes files amongst them, offering as output the union "subvolume".
Gluster uses this translator by default, but there are some that aren't
and might be useful for us, such as a translator that creates a block
device for us. Unfortunately the documentation here is lacking.

This will however need to wait for larger availability of QEMU version
1.3+ in our supported distributions. On Debian Wheezy, userspace support
requires compiling from source `both` QEMU (version 1.3 or newer) `and`
Gluster (the packaged version does not build a library required for QEMU
support). Right now there are likely more pressing priorities such as
support for QEMU 1.6 in the upcoming Ubuntu 14.04 release.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
