import unittest

from src.image_processor import PillowImageProcessor


class ImageProcessorTest(unittest.TestCase):
    def test_png_does_not_receive_jpeg_quality_parameter(self):
        processor = PillowImageProcessor(image_format="png")
        calls = []

        class FakeImage:
            mode = "RGB"

            def save(self, path, format, **kwargs):
                calls.append((path, format, kwargs))

        processor._save(FakeImage(), "unused.png", 82)
        self.assertEqual(calls[0][1], "PNG")
        self.assertNotIn("quality", calls[0][2])
        self.assertTrue(calls[0][2]["optimize"])

