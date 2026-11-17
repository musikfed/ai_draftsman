"""Disk display should only contain useful user partitions, not Snap loop mounts."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from studio.monitor import disk_snapshot


class DiskMonitorTests(unittest.TestCase):
    def test_only_real_partitions(self):
        entries = [
            SimpleNamespace(device="/dev/sda3", mountpoint="/", fstype="ext4"),
            SimpleNamespace(device="/dev/nvme1n1p2", mountpoint="/1tbdisk", fstype="ext4"),
            SimpleNamespace(device="/dev/loop0", mountpoint="/snap/bare/5", fstype="squashfs"),
            SimpleNamespace(device="/dev/loop1", mountpoint="/snap/chromium/3563", fstype="squashfs"),
            SimpleNamespace(device="/dev/sda1", mountpoint="/boot/efi", fstype="vfat"),
            SimpleNamespace(device="tmpfs", mountpoint="/run", fstype="tmpfs"),
        ]
        usage = SimpleNamespace(total=1024**3, used=512*1024**2,
                                free=512*1024**2, percent=50.0)
        with patch("studio.monitor.psutil.disk_partitions", return_value=entries), \
             patch("studio.monitor.psutil.disk_usage", return_value=usage) as measure:
            disks = disk_snapshot()

        self.assertEqual([d["mount"] for d in disks], ["/", "/1tbdisk"])
        self.assertEqual(measure.call_count, 2)
        self.assertEqual(disks[0]["percent"], 50.0)

    def test_loop_device_excluded_even_without_snap_mount(self):
        entries=[SimpleNamespace(device="/dev/loop12",mountpoint="/mnt/loop",fstype="ext4"),
                 SimpleNamespace(device="/dev/mapper/data",mountpoint="/data",fstype="ext4")]
        usage=SimpleNamespace(total=4096, used=2048, free=2048, percent=50)
        with patch("studio.monitor.psutil.disk_partitions",return_value=entries), \
             patch("studio.monitor.psutil.disk_usage",return_value=usage):
            disks=disk_snapshot()
        self.assertEqual([d["mount"] for d in disks], ["/data"])


if __name__ == "__main__":
    unittest.main()
