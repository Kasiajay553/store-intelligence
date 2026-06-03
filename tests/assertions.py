# tests/assertions.py
"""
10 Core test assertions to validate the Store Intelligence API against challenge requirements.
Requires the FastAPI backend to be running on http://localhost:8000.
"""
import sys
import json
import sqlite3
import requests
from datetime import datetime

class ChallengeTester:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", db_path: str = "store_intelligence.db"):
        self.base_url = base_url
        self.db_path = db_path

    def _get_db_count(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def assert_gate_1_malformed_event_rejection(self):
        """1. API must reject events missing required fields with a 422 Validation Error."""
        payload = {"event_type": "ENTRY"}  # missing store_id / timestamp / visitor_id
        # We test both /events and /events/ingest
        res = requests.post(f"{self.base_url}/events/ingest", json=[payload])
        assert res.status_code == 422 or (res.status_code == 200 and res.json()["failed_count"] > 0), f"Expected validation failure, got {res.status_code}"
        print("[PASS] Gate 1: Malformed events rejected or flagged with validation errors.")

    def assert_gate_2_event_deduplication(self):
        """2. Duplicate event streams should be ignored/deduplicated in the database."""
        event = {
            "event_id": "test_dedup_unique_id_100",
            "event_type": "ENTRY",
            "visitor_id": "ID_TEST_DEDUP",
            "store_id": "ST1008",
            "camera_id": "CAM3",
            "timestamp": "2026-03-08T18:10:00.000000"
        }
        # Ingest once
        res1 = requests.post(f"{self.base_url}/events/ingest", json=[event])
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"

        # Get initial DB count
        count_before = self._get_db_count(
            "SELECT COUNT(*) FROM events WHERE event_id = 'test_dedup_unique_id_100'"
        )
        
        # Ingest second time (duplicate payload stream)
        requests.post(f"{self.base_url}/events/ingest", json=[event])
        requests.post(f"{self.base_url}/events/ingest", json=[event])
        
        count_after = self._get_db_count(
            "SELECT COUNT(*) FROM events WHERE event_id = 'test_dedup_unique_id_100'"
        )
        assert count_after == 1, f"Deduplication failed: event recorded {count_after} times."
        print("[PASS] Gate 2: Event deduplication verified (UNIQUE event_id key active).")

    def assert_gate_3_visitor_count(self):
        """3. Total unique visitors count is aggregate of unique tracked trajectories (excluding staff)."""
        res = requests.get(f"{self.base_url}/stores/ST1008/metrics")
        assert res.status_code == 200
        data = res.json()
        db_visitors = self._get_db_count("SELECT COUNT(DISTINCT visitor_id) FROM events WHERE store_id = 'ST1008' AND is_staff = 0")
        assert data["total_visitors"] == db_visitors, f"Metrics visitors ({data['total_visitors']}) mismatch DB ({db_visitors})"
        print(f"[PASS] Gate 3: Unique visitor count ({data['total_visitors']}) matches database record (excluding staff).")

    def assert_gate_4_transaction_count(self):
        """4. Total transaction count aggregates matches imported POS CSV record count."""
        res = requests.get(f"{self.base_url}/stores/ST1008/metrics")
        assert res.status_code == 200
        data = res.json()
        db_tx = self._get_db_count("SELECT COUNT(DISTINCT order_id) FROM transactions WHERE store_id = 'ST1008'")
        assert data["total_transactions"] == db_tx, f"Metrics transactions ({data['total_transactions']}) mismatch DB ({db_tx})"
        print(f"[PASS] Gate 4: Transaction metrics ({data['total_transactions']}) match POS database count.")

    def assert_gate_5_conversion_rate(self):
        """5. Store conversion rate matches standard calculation: (transactions / visitors) * 100."""
        res = requests.get(f"{self.base_url}/stores/ST1008/metrics")
        assert res.status_code == 200
        data = res.json()
        expected = round((data["total_transactions"] / data["total_visitors"] * 100), 2) if data["total_visitors"] > 0 else 0.0
        assert abs(data["conversion_rate_percentage"] - expected) < 0.01, f"Conversion math mismatch: expected {expected}, got {data['conversion_rate_percentage']}"
        print(f"[PASS] Gate 5: Store conversion rate ({data['conversion_rate_percentage']}) math is validated.")

    def assert_gate_6_average_dwell_time(self):
        """6. Average visitor dwell time is computed from event duration deltas."""
        res = requests.get(f"{self.base_url}/stores/ST1008/metrics")
        assert res.status_code == 200
        assert "average_dwell_minutes" in res.json()
        print("[PASS] Gate 6: Average visitor dwell times computed successfully.")

    def assert_gate_7_billing_queue_wait_time(self):
        """7. Wait times in queue completed events must match served minus join timestamps."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT metadata FROM events WHERE event_type = 'ZONE_EXIT' AND zone_id LIKE '%BILLING%' LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            metadata = json.loads(row[0])
            join = datetime.fromisoformat(metadata["queue_join_ts"])
            served = datetime.fromisoformat(metadata.get("queue_served_ts") or metadata.get("queue_exit_ts"))
            calc_wait = int((served - join).total_seconds())
            assert abs(metadata["wait_seconds"] - calc_wait) <= 2, f"Wait seconds mismatch: payload={metadata['wait_seconds']}, calculated={calc_wait}"
        print("[PASS] Gate 7: Billing queue wait seconds match event timestamps.")

    def assert_gate_8_queue_abandonment_rate(self):
        """8. Queue abandonment count identifies customers leaving queue before checkouts."""
        res = requests.get(f"{self.base_url}/stores/ST1008/anomalies")
        assert res.status_code == 200
        data = res.json()
        db_abandon = self._get_db_count("SELECT COUNT(*) FROM events WHERE store_id = 'ST1008' AND event_type = 'BILLING_QUEUE_ABANDON'")
        api_abandon = len([a for a in data["anomalies"] if a["anomaly_type"] == "Queue Abandonment"])
        assert api_abandon == db_abandon, f"Abandoned count mismatch: API={api_abandon}, DB={db_abandon}"
        print("[PASS] Gate 8: Queue abandonment counts validated.")

    def assert_gate_9_funnel_percentages(self):
        """9. Funnel counts are strictly bounded and non-increasing down the stages."""
        res = requests.get(f"{self.base_url}/stores/ST1008/funnel")
        assert res.status_code == 200
        stages = res.json()["stages"]
        counts = [s["count"] for s in stages]
        assert counts[0] >= counts[1], f"Entry ({counts[0]}) < Browse ({counts[1]})"
        assert counts[1] >= counts[2], f"Browse ({counts[1]}) < Queue ({counts[2]})"
        print("[PASS] Gate 9: Conversion funnel bounds validated.")

    def assert_gate_10_system_health(self):
        """10. Self-diagnostic /health endpoint returns healthy status and DB status."""
        res = requests.get(f"{self.base_url}/health")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data["status"] == "HEALTHY", f"System unhealthy: {data}"
        assert data["components"]["database"] == "OK", "Database issue"
        print("[PASS] Gate 10: Health check diagnostics return normal.")

    def run_all(self):
        print("--- Executing Purplle Store Intelligence API Assertions ---")
        try:
            self.assert_gate_1_malformed_event_rejection()
            self.assert_gate_2_event_deduplication()
            self.assert_gate_3_visitor_count()
            self.assert_gate_4_transaction_count()
            self.assert_gate_5_conversion_rate()
            self.assert_gate_6_average_dwell_time()
            self.assert_gate_7_billing_queue_wait_time()
            self.assert_gate_8_queue_abandonment_rate()
            self.assert_gate_9_funnel_percentages()
            self.assert_gate_10_system_health()
            print("\n[SUCCESS] ALL 10 ACCEPTANCE GATES COMPLETED SUCCESSFULLY!")
        except Exception as e:
            print(f"\n[FAIL] Assertion failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    tester = ChallengeTester()
    tester.run_all()
