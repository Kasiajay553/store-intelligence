# tests/test_metrics.py
# PROMPT: Standardize store metrics engine unit tests and prevent Windows file locking failures.
# CHANGES MADE: Added # PROMPT: and # CHANGES MADE: blocks. Integrated random database naming suffix and safe try-except cleanup blocks to circumvent PermissionError on Windows.
"""
Unit tests for store metrics engine.
Uses an isolated SQLite database to verify visitor conversions and revenues.
"""
import os
import unittest
import sqlite3
import random
from app.ingestion import IngestionEngine
from app.models import EventPayload
from app.metrics import MetricsEngine

class TestMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use a unique database file name per test run to prevent concurrent process lock issues on Windows
        cls.test_db = f"test_store_intelligence_metrics_{random.randint(10000, 99999)}.db"
        
        try:
            if os.path.exists(cls.test_db):
                os.remove(cls.test_db)
        except:
            pass

        cls.ingestion = IngestionEngine(cls.test_db)
        cls.metrics = MetricsEngine(cls.test_db)

        # Ingest test transaction
        conn = sqlite3.connect(cls.test_db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO transactions 
            (order_id, order_date, order_time, order_timestamp, store_id, product_id, brand_name, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (999, "2026-03-08", "12:00:00", "2026-03-08T12:00:00", "ST1076", "400400", "Purplle Test", 1500.0))
        conn.commit()
        conn.close()

        # Ingest test entry event
        cls.ingestion.ingest(EventPayload(
            event_id="ev_t_entry_001",
            store_id="ST1076",
            camera_id="cam1",
            visitor_id="ID_999",
            event_type="ENTRY",
            timestamp="2026-03-08T11:50:00",
            is_staff=False,
            confidence=0.9
        ))
        
        # Ingest zone entry/exit events to simulate dwell
        cls.ingestion.ingest(EventPayload(
            event_id="ev_t_entry_002",
            store_id="ST1076",
            camera_id="CAM2",
            visitor_id="ID_999",
            event_type="ZONE_ENTER",
            zone_id="PURPLLE_MUM_1076_Z01",
            timestamp="2026-03-08T11:52:00",
            is_staff=False,
            confidence=0.9,
            metadata={"zone_name": "Left Shelf"}
        ))
        
        cls.ingestion.ingest(EventPayload(
            event_id="ev_t_entry_003",
            store_id="ST1076",
            camera_id="CAM2",
            visitor_id="ID_999",
            event_type="ZONE_EXIT",
            zone_id="PURPLLE_MUM_1076_Z01",
            timestamp="2026-03-08T12:05:00",
            dwell_ms=13 * 60 * 1000, # 13 minutes in ms
            is_staff=False,
            confidence=0.9,
            metadata={"zone_name": "Left Shelf"}
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.test_db):
                os.remove(cls.test_db)
        except:
            pass

    def test_visitor_count_calculation(self):
        """Verify unique visitor aggregation counts."""
        res = self.metrics.compute_metrics("ST1076", "2026-03-08")
        self.assertEqual(res["total_visitors"], 1)

    def test_revenue_and_transactions_aggregation(self):
        """Verify transactions count and revenue sum aggregates."""
        res = self.metrics.compute_metrics("ST1076", "2026-03-08")
        self.assertEqual(res["total_transactions"], 1)
        self.assertEqual(res["total_revenue"], 1500.0)

    def test_conversion_rate_math(self):
        """Verify store conversion percentage equals 100% since 1 transaction / 1 visitor."""
        res = self.metrics.compute_metrics("ST1076", "2026-03-08")
        self.assertEqual(res["conversion_rate_percentage"], 100.0)

    def test_average_dwell_minutes(self):
        """Verify dwell time is calculated correctly (11:50:00 to 12:05:00 is 15 minutes)."""
        res = self.metrics.compute_metrics("ST1076", "2026-03-08")
        self.assertEqual(res["average_dwell_minutes"], 15.0)

if __name__ == "__main__":
    unittest.main()
