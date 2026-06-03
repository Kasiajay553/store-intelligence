# app/anomalies.py
"""
Anomaly detection engine.
Analyzes event logs and transactions to identify queue spikes, conversion drops, dead zones, and layout bottlenecks.
Uses compliant severities (INFO, WARN, CRITICAL) and provides suggested actions.
"""
import json
import sqlite3
from datetime import datetime

class AnomalyEngine:
    def __init__(self, db_path: str = "store_intelligence.db"):
        self.db_path = db_path

    def detect_anomalies(self, store_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check date presence in events
        cursor.execute("SELECT COUNT(*) FROM events WHERE store_id = ? AND date(timestamp) = ?", (store_id, date))
        event_count = cursor.fetchone()[0]
        use_fallback = (event_count == 0)

        # Filters
        if use_fallback:
            event_filter = "store_id = ? AND is_staff = 0"
            tx_filter = "store_id = ?"
            params = (store_id,)
        else:
            event_filter = "store_id = ? AND date(timestamp) = ? AND is_staff = 0"
            tx_filter = "store_id = ? AND date(order_timestamp) = ?"
            params = (store_id, date)

        anomalies_list = []

        # 1. Check total visitors and transactions for Conversion Drop
        cursor.execute(f"SELECT COUNT(DISTINCT visitor_id) FROM events WHERE {event_filter}", params)
        visitors = cursor.fetchone()[0] or 0
        
        cursor.execute(f"SELECT COUNT(DISTINCT order_id) FROM transactions WHERE {tx_filter}", params)
        transactions = cursor.fetchone()[0] or 0
        
        conversion_rate = (transactions / visitors * 100) if visitors > 0 else 0.0
        
        # Rule: Conversion Drop (CRITICAL)
        if visitors >= 3 and conversion_rate < 10.0:
            anomalies_list.append({
                "anomaly_type": "Conversion Drop",
                "severity": "CRITICAL",
                "timestamp": datetime.now().isoformat(),
                "details": f"Conversion rate is extremely low at {round(conversion_rate, 2)}% ({transactions} sales out of {visitors} visitors).",
                "suggested_action": "Audit checkout counters, verify POS connection state, or offer digital coupons to checkout queues."
            })

        # 2. Check Queue Spike (depth or wait time)
        # Depth check: active joins without exits
        cursor.execute(f"""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE {event_filter} AND event_type = 'BILLING_QUEUE_JOIN'
            AND visitor_id NOT IN (
                SELECT DISTINCT visitor_id FROM events
                WHERE {event_filter} AND event_type IN ('BILLING_QUEUE_ABANDON', 'ZONE_EXIT') AND zone_id LIKE '%BILLING%'
            )
        """, params + params)
        queue_depth = cursor.fetchone()[0] or 0
        
        # Wait time check: average wait time in queue exits
        cursor.execute(f"""
            SELECT AVG(dwell_ms) FROM events
            WHERE {event_filter} AND event_type = 'ZONE_EXIT' AND zone_id LIKE '%BILLING%'
        """, params)
        avg_wait_ms = cursor.fetchone()[0] or 0.0
        avg_wait_sec = avg_wait_ms / 1000.0

        if queue_depth > 3 or avg_wait_sec > 30.0:
            anomalies_list.append({
                "anomaly_type": "Queue Spike",
                "severity": "WARN",
                "timestamp": datetime.now().isoformat(),
                "details": f"Billing line spike detected. Queue depth is {queue_depth} active visitors. Avg wait is {round(avg_wait_sec, 1)} seconds.",
                "suggested_action": "Open an additional billing counter immediately to reduce customer wait time."
            })

        # 3. Check for Dead Zones
        # Get all zones configured for this store in layout
        # (We will use layout zone list or fallback to known zones)
        known_zones = []
        if store_id == "ST1076":
            known_zones = ["PURPLLE_MUM_1076_Z01", "PURPLLE_MUM_1076_Z02", "PURPLLE_MUM_1076_Z03"]
        else: # ST1008
            known_zones = ["PURPLLE_ST1008_Z01", "PURPLLE_ST1008_Z02"]
            
        for zone in known_zones:
            cursor.execute(f"""
                SELECT COUNT(*) FROM events 
                WHERE {event_filter} AND zone_id = ? AND event_type = 'ZONE_ENTER'
            """, params + (zone,))
            traffic = cursor.fetchone()[0] or 0
            
            if traffic == 0 and visitors >= 3:
                anomalies_list.append({
                    "anomaly_type": "Dead Zone",
                    "severity": "INFO",
                    "timestamp": datetime.now().isoformat(),
                    "details": f"Zone '{zone}' recorded zero visitor interactions despite active store footfalls.",
                    "suggested_action": "Improve store layout, place popular items or promotional banners in this area."
                })

        # 4. Long Billing Queue Wait Times (> 15 seconds)
        cursor.execute(f"""
            SELECT visitor_id, timestamp, dwell_ms
            FROM events
            WHERE {event_filter} AND event_type = 'ZONE_EXIT' AND zone_id LIKE '%BILLING%'
        """, params)
        
        for row in cursor.fetchall():
            dwell_ms = row[2] or 0
            wait_sec = int(dwell_ms / 1000.0)
            if wait_sec > 15:
                anomalies_list.append({
                    "anomaly_type": "Long Billing Wait",
                    "severity": "WARN",
                    "timestamp": row[1],
                    "details": f"Customer visitor {row[0]} waited in queue for {wait_sec} seconds (threshold: 15s).",
                    "suggested_action": "Open a dynamic cashier station or allocate an checkout helper."
                })

        # 5. Queue Abandonment
        cursor.execute(f"""
            SELECT visitor_id, timestamp, dwell_ms
            FROM events
            WHERE {event_filter} AND event_type = 'BILLING_QUEUE_ABANDON'
        """, params)
        
        for row in cursor.fetchall():
            dwell_ms = row[2] or 0
            wait_sec = int(dwell_ms / 1000.0)
            anomalies_list.append({
                "anomaly_type": "Queue Abandonment",
                "severity": "CRITICAL",
                "timestamp": row[1],
                "details": f"Customer visitor {row[0]} abandoned the billing queue after waiting {wait_sec} seconds.",
                "suggested_action": "Verify if wait times are causing high friction; review customer service levels."
            })

        # 6. Layout Bottleneck (Zone average dwell time > 45 seconds)
        cursor.execute(f"""
            SELECT zone_id, AVG(dwell_ms)
            FROM events
            WHERE {event_filter} AND event_type = 'ZONE_EXIT' AND zone_id IS NOT NULL AND zone_id NOT LIKE '%BILLING%'
            GROUP BY zone_id
        """, params)
        
        for row in cursor.fetchall():
            zone = row[0]
            avg_dwell_sec = (row[1] or 0.0) / 1000.0
            if avg_dwell_sec > 45.0:
                anomalies_list.append({
                    "anomaly_type": "Layout Bottleneck",
                    "severity": "INFO",
                    "timestamp": datetime.now().isoformat(),
                    "details": f"Zone '{zone}' shows high dwell friction. Average customer stay is {round(avg_dwell_sec, 1)} seconds.",
                    "suggested_action": "Rearrange shelf density or create wider aisles to clear traffic congestion."
                })

        conn.close()

        return {
            "store_id": store_id,
            "query_date": date,
            "using_fallback_aggregates": use_fallback,
            "anomalies": anomalies_list
        }
