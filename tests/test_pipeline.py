# tests/test_pipeline.py
# PROMPT: Standardize CV pipeline unit tests and add prompt blocks.
# CHANGES MADE: Added # PROMPT: and # CHANGES MADE: blocks. Cleaned up comments and standard tracking assertions.
"""
Tests for the CV pipeline components including tracking and store layout loading.
"""
import unittest
from pipeline.tracker import CentroidTracker
from pipeline.detect import load_store_layout, is_point_in_polygon

class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tracker = CentroidTracker(max_disappeared=5, min_iou=0.1)

    def test_tracker_initialization(self):
        """Verify tracker starts with correct empty structures."""
        self.assertEqual(len(self.tracker.objects), 0)
        self.assertEqual(self.tracker.next_object_id, 100)

    def test_tracker_registration(self):
        """Verify tracker registers new bboxes."""
        bboxes = [[10, 10, 50, 50]]
        tracked = self.tracker.update(bboxes)
        self.assertEqual(len(tracked), 1)
        self.assertIn(100, tracked)
        self.assertEqual(tracked[100][0], bboxes[0])

    def test_point_in_polygon_check(self):
        """Verify point-in-polygon geometry checks work."""
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
        self.assertTrue(is_point_in_polygon((5, 5), polygon))
        self.assertFalse(is_point_in_polygon((15, 5), polygon))

    def test_layout_loading(self):
        """Verify store layout loader reads JSON layout file correctly."""
        layout = load_store_layout("store_layout.json")
        self.assertIn("stores", layout)
        self.assertIn("ST1008", layout["stores"])

if __name__ == "__main__":
    unittest.main()
