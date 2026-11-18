"""No-network, no-GPU tests for monitored downloads and process diagnostics."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from studio import downloads, monitor
from studio.checkpoints import CHECKPOINTS


class CheckpointDownloadTests(unittest.TestCase):
    def test_models_have_known_sha256(self):
        for mid, metadata in CHECKPOINTS.items():
            with self.subTest(mid=mid):
                self.assertEqual(len(metadata["expected_sha256"]), 64)
                self.assertGreater(metadata["expected_size_bytes"], 6_500_000_000)

    def test_existing_hash_mismatch_never_destroys_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.safetensors"
            path.write_bytes(b"not a real model")
            cfg = {"expected_sha256": "0" * 64, "expected_size_bytes": 6_940_000_000}
            with patch.object(downloads, "get_checkpoint", return_value=(path, cfg)):
                with self.assertRaisesRegex(RuntimeError, "hash differs"):
                    downloads.download_checkpoint("sample", lambda _: None)
            self.assertEqual(path.read_bytes(), b"not a real model")

    def test_check_space_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.safetensors"
            cfg = {"expected_sha256": "0" * 64, "expected_size_bytes": 6_940_000_000}
            class Usage:
                free = 4 * 1024**3
            with patch.object(downloads, "get_checkpoint", return_value=(path, cfg)), \
                 patch.object(downloads.shutil, "disk_usage", return_value=Usage()), \
                 patch.object(downloads.requests, "get") as get:
                with self.assertRaisesRegex(RuntimeError, "Not enough free space"):
                    downloads.download_checkpoint("sample", lambda _: None)
                get.assert_not_called()

    def test_sha256_small_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a"
            f.write_bytes(b"test")
            self.assertEqual(downloads._digest(f), hashlib.sha256(b"test").hexdigest())


class HostTelemetryTests(unittest.TestCase):
    def test_endpoint_has_real_resource_keys(self):
        sample = {
            "cpu":{"percent":14.5,"logical_threads":32,"physical_cores":16,"load_average":[1,2,3]},
            "ram":{"percent":30,"used_mib":14000,"total_mib":47000},
            "swap":{"percent":0,"used_mib":0,"total_mib":35000},
            "gpu":{"devices":[{"vram_used_mib":4096,"vram_total_mib":12288,
                               "vram_percent":33.3,"utilization_percent":61,
                               "temperature_c":65,"power_w":110}],
                    "processes":[{"pid":123,"vram_mib":3000}]},
            "processes":[{"pid":123,"role":"Diffusers / генерация","name":"python",
                           "ram_mib":5000,"vram_mib":3000,"cpu_percent":123.5}],
            "disks":[],"zombies":{"count":0,"examples":[]}
        }
        with patch.object(app, "collect_snapshot", return_value=sample), \
             patch.object(app, "current_job", return_value={"pid":123}), \
             patch.object(app, "reach", return_value=False):
            response = app.app.test_client().get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["processes"][0]["ram_mib"], 5000)
        self.assertEqual(data["processes"][0]["vram_mib"], 3000)
        self.assertTrue(data["engine_busy"])


if __name__ == "__main__":
    unittest.main()
