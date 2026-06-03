# tests/test_special.py
# PROMPT: Implement special test scenarios (empty store, all-staff clip, zero purchases, re-entry funnel) for compliance validation.
# CHANGES MADE: Created tests/test_special.py with the four required test scenarios, isolating sqlite3 database for assertions, and including prompt blocks. Cleared transactions database in empty store and zero purchases tests to bypass auto-import logic.
"""
Special compliance tests:
1. Empty store metrics check
2. All staff clip metrics check (should exclude staff and return 0 visitors)
3. Zero purchases conversion check (should return 0% conversion)
4. Re-entry funnel check (should deduplicate multiple entries for same visitor)
"""
import os
import unittest
import sqlite3
import random
from app.ingestion import IngestionEngine
from app.models import EventPayload
from app.metrics import MetricsEngine
from app.funnel import FunnelEngine

class TestSpecialScenarios(unittest.TestCase):
    def setUp(self):
        self.test_db = f"test_store_intelligence_special_{random.randint(10000, 99999)}.db"
        self.ingestion = IngestionEngine(self.test_db)
        self.metrics = MetricsEngine(self.test_db)
        self.funnel = FunnelEngine(self.test_db)

    def tearDown(self):
        try:
            if os.path.exists(self.test_db):
                os.remove(self.test_db)
        except:
            pass

    def test_empty_store(self):
        """Verify metrics and funnel returned for an empty store."""
        # Clear auto-imported transactions for empty store check
        conn = sqlite3.connect(self.test_db)
        conn.execute("DELETE FROM transactions")
        conn.commit()
        conn.close()

        res_metrics = self.metrics.compute_metrics("ST1008", "2026-03-08")
        self.assertEqual(res_metrics["total_visitors"], 0)
        self.assertEqual(res_metrics["total_transactions"], 0)
        self.assertEqual(res_metrics["conversion_rate_percentage"], 0.0)

        res_funnel = self.funnel.compute_funnel("ST1008", "2026-03-08")
        self.assertEqual(res_funnel["stages"][0]["count"], 0)
        self.assertEqual(res_funnel["stages"][3]["count"], 0)

    def test_all_staff_clip(self):
        """Verify that when all events contain is_staff=True, visitor metrics return 0."""
        # Ingest staff entry
        self.ingestion.ingest(EventPayload(
            event_id="staff_ev_1",
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="ID_STAFF_1",
            event_type="ENTRY",
            timestamp="2026-03-08T18:10:00",
            is_staff=True,
            confidence=0.9
        ))
        # Ingest staff zone activity
        self.ingestion.ingest(EventPayload(
            event_id="staff_ev_2",
            store_id="ST1008",
            camera_id="CAM1",
            visitor_id="ID_STAFF_1",
            event_type="ZONE_ENTER",
            zone_id="PURPLLE_ST1008_Z01",
            timestamp="2026-03-08T18:11:00",
            is_staff=True,
            confidence=0.9
        ))
        
        # Verify metrics (should exclude staff and show 0 visitors)
        res = self.metrics.compute_metrics("ST1008", "2026-03-08")
        self.assertEqual(res["total_visitors"], 0)
        
        # Verify funnel (should exclude staff and show 0 counts)
        res_funnel = self.funnel.compute_funnel("ST1008", "2026-03-08")
        self.assertEqual(res_funnel["stages"][0]["count"], 0)

    def test_zero_purchases(self):
        """Verify conversion rate is 0% when there are visitors but zero transactions."""
        # Clear auto-imported transactions
        conn = sqlite3.connect(self.test_db)
        conn.execute("DELETE FROM transactions")
        conn.commit()
        conn.close()

        # Ingest standard visitor entry
        self.ingestion.ingest(EventPayload(
            event_id="visitor_ev_1",
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="ID_VISITOR_1",
            event_type="ENTRY",
            timestamp="2026-03-08T18:10:00",
            is_staff=False,
            confidence=0.9
        ))
        
        # No transactions are loaded into database
        res = self.metrics.compute_metrics("ST1008", "2026-03-08")
        self.assertEqual(res["total_visitors"], 1)
        self.assertEqual(res["total_transactions"], 0)
        self.assertEqual(res["conversion_rate_percentage"], 0.0)

    def test_reentry_funnel_deduplication(self):
        """Verify that multiple entries for the same visitor_id are deduplicated in the funnel."""
        # Ingest first entry
        self.ingestion.ingest(EventPayload(
            event_id="reentry_ev_1",
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="ID_RETURN_1",
            event_type="ENTRY",
            timestamp="2026-03-08T18:10:00",
            is_staff=False,
            confidence=0.9
        ))
        # Ingest zone browse
        self.ingestion.ingest(EventPayload(
            event_id="reentry_ev_2",
            store_id="ST1008",
            camera_id="CAM1",
            visitor_id="ID_RETURN_1",
            event_type="ZONE_ENTER",
            zone_id="PURPLLE_ST1008_Z01",
            timestamp="2026-03-08T18:11:00",
            is_staff=False,
            confidence=0.9
        ))
        # Ingest exit
        self.ingestion.ingest(EventPayload(
            event_id="reentry_ev_3",
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="ID_RETURN_1",
            event_type="EXIT",
            timestamp="2026-03-08T18:15:00",
            is_staff=False,
            confidence=0.9
        ))
        
        # Ingest second entry (re-entry) 20 minutes later
        self.ingestion.ingest(EventPayload(
            event_id="reentry_ev_4",
            store_id="ST1008",
            camera_id="CAM3",
            visitor_id="ID_RETURN_1",
            event_type="REENTRY",
            timestamp="2026-03-08T18:35:00",
            is_staff=False,
            confidence=0.9
        ))
        
        res_funnel = self.funnel.compute_funnel("ST1008", "2026-03-08")
        # Stage 1 (Entry) must be 1, because ID_RETURN_1 is deduplicated
        self.assertEqual(res_funnel["stages"][0]["count"], 1)
        self.assertEqual(res_funnel["stages"][1]["count"], 1)

if __name__ == "__main__":
    unittest.main()
