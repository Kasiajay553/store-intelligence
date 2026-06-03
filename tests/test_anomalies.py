# tests/test_anomalies.py
# PROMPT: Standardize anomaly detection engine unit tests and prevent Windows file locking failures.
# CHANGES MADE: Added # PROMPT: and # CHANGES MADE: blocks. Integrated random database naming suffix and safe try-except cleanup blocks to circumvent PermissionError on Windows.
"""
Unit tests for the operational anomaly detection rules.
Uses an isolated SQLite database to verify wait queues and abandonments.
"""
import os
import unittest
import random
from app.ingestion import IngestionEngine
from app.models import EventPayload
from app.anomalies import AnomalyEngine

class TestAnomalies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use a unique database file name per test run to prevent concurrent process lock issues on Windows
        cls.test_db = f"test_store_intelligence_anom_{random.randint(10000, 99999)}.db"
        
        try:
            if os.path.exists(cls.test_db):
                os.remove(cls.test_db)
        except:
            pass

        cls.ingestion = IngestionEngine(cls.test_db)
        cls.anomalies = AnomalyEngine(cls.test_db)

        # Ingest a completed queue event with long wait (e.g. 45 seconds > threshold of 15 seconds)
        cls.ingestion.ingest(EventPayload(
            event_id="ev_t_anom_001",
            store_id="ST1076",
            camera_id="CAM6",
            visitor_id="ID_150",
            event_type="ZONE_EXIT",
            zone_id="PURPLLE_MUM_1076_Z_BILLING_01",
            timestamp="2026-03-08T18:00:45",
            dwell_ms=45000,
            is_staff=False,
            confidence=0.9,
            metadata={"zone_name": "Billing Counter Queue"}
        ))

        # Ingest an abandoned queue event
        cls.ingestion.ingest(EventPayload(
            event_id="ev_t_anom_002",
            store_id="ST1076",
            camera_id="CAM6",
            visitor_id="ID_151",
            event_type="BILLING_QUEUE_ABANDON",
            zone_id="PURPLLE_MUM_1076_Z_BILLING_01",
            timestamp="2026-03-08T18:06:10",
            dwell_ms=70000,
            is_staff=False,
            confidence=0.9,
            metadata={"zone_name": "Billing Counter Queue"}
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.test_db):
                os.remove(cls.test_db)
        except:
            pass

    def test_long_queue_wait_detection(self):
        """Verify wait times above threshold are flagged as anomalies."""
        res = self.anomalies.detect_anomalies("ST1076", "2026-03-08")
        long_wait_alerts = [a for a in res["anomalies"] if a["anomaly_type"] == "Long Billing Wait"]
        self.assertEqual(len(long_wait_alerts), 1)
        self.assertIn("waited in queue for 45 seconds", long_wait_alerts[0]["details"])

    def test_queue_abandonment_detection(self):
        """Verify queue abandonments are flagged as anomalies."""
        res = self.anomalies.detect_anomalies("ST1076", "2026-03-08")
        abandon_alerts = [a for a in res["anomalies"] if a["anomaly_type"] == "Queue Abandonment"]
        self.assertEqual(len(abandon_alerts), 1)
        self.assertIn("abandoned the billing queue after waiting 70 seconds", abandon_alerts[0]["details"])

if __name__ == "__main__":
    unittest.main()
