"""GPU-free tests of manual/semantic image variants and SDXL model selection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.parameters import choose_variants, extract_variant_count, MAX_VARIANTS
from studio.checkpoints import CHECKPOINTS, DEFAULT_CHECKPOINT, get_checkpoint, list_checkpoints
from app import app


class ParametersTests(unittest.TestCase):
    def test_number_in_russian_description(self):
        self.assertEqual(choose_variants("auto", "Сделай 7 вариантов рыжего котёнка"), 7)
        self.assertEqual(choose_variants("авто", "нарисуй семь вариантов"), 7)
        self.assertEqual(choose_variants(None, "вариантов: 8"), 8)
        self.assertEqual(choose_variants("auto", "Please create five images"), 5)

    def test_slides_not_confused_with_variants(self):
        self.assertIsNone(extract_variant_count("Урок 13: пять слайдов для комикса"))
        self.assertEqual(choose_variants("auto", "Урок 13: пять слайдов"), 1)

    def test_manual_override_and_limits(self):
        self.assertEqual(choose_variants("3", "Нарисуй 17 вариантов"), 3)
        self.assertEqual(choose_variants(48, "любая тема"), MAX_VARIANTS)
        for illegal in ("0", "49", "много", -1, 100):
            with self.subTest(value=illegal), self.assertRaises(ValueError):
                choose_variants(illegal, "котёнок")

    def test_known_models_only(self):
        self.assertEqual(len(CHECKPOINTS), 2)
        self.assertEqual(get_checkpoint(DEFAULT_CHECKPOINT)[1]["family"], "SDXL")
        with self.assertRaises(ValueError):
            get_checkpoint("fake-pipeline-or-path")

    def test_catalog_does_not_start_download(self):
        with app.test_client() as client:
            response=client.get("/api/images/models")
            self.assertEqual(response.status_code, 200)
            data=response.get_json()
            self.assertEqual(len(data["models"]), 2)
            self.assertEqual(data["default"], DEFAULT_CHECKPOINT)
            self.assertTrue(all("installed" in item for item in data["models"]))
            wrong=client.post("/api/images/models/download", json={"model":"fake"})
            self.assertEqual(wrong.status_code, 400)


if __name__=="__main__":
    unittest.main()
