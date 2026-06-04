# app/metrics.py
"""
Metrics aggregation engine.
Executes analytical SQL queries to compute visitors, transaction rates, dwell times, and revenues.
Excludes staff from all visitor metrics.
"""
import sqlite3
import json
from datetime import datetime

class MetricsEngine:
    def __init__(self, db_path: str = "store_intelligence.db"):
        self.db_path = db_path

    def compute_metrics(self, store_id: str, date: str) -> dict:
        """
        Calculates KPIs for a store on a given date.
        Excludes staff (is_staff = 1) from all calculations.
        If no direct date match exists in both datasets (due to challenge dataset differences),
        it falls back to computing across all available dates to show active data.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Check date presence in events
        cursor.execute("SELECT COUNT(*) FROM events WHERE store_id = ? AND date(timestamp) = ?", (store_id, date))
        event_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM transactions WHERE store_id = ? AND date(order_timestamp) = ?", (store_id, date))
        tx_count = cursor.fetchone()[0]

        use_fallback = (event_count == 0 or tx_count == 0)
        query_date_str = date

        # Base filters
        if use_fallback:
            event_filter = "store_id = ? AND is_staff = 0"
            tx_filter = "store_id = ?"
            params = (store_id,)
            tx_params = (store_id,)
        else:
            event_filter = "store_id = ? AND date(timestamp) = ? AND is_staff = 0"
            tx_filter = "store_id = ? AND date(order_timestamp) = ?"
            params = (store_id, date)
            tx_params = (store_id, date)

        # Compute unique visitors (excluding staff)
        cursor.execute(f"SELECT COUNT(DISTINCT visitor_id) FROM events WHERE {event_filter}", params)
        visitors = cursor.fetchone()[0] or 0

        # Compute total transactions and revenue
        cursor.execute(f"SELECT COUNT(DISTINCT order_id), SUM(total_amount) FROM transactions WHERE {tx_filter}", tx_params)
        tx_result = cursor.fetchone()
        transactions = tx_result[0] or 0
        revenue = round(tx_result[1] or 0.0, 2)

        # Compute global average dwell time (in minutes, excluding staff)
        # We group events chronologically by visitor_id to detect distinct visits
        cursor.execute(f"""
            SELECT visitor_id, timestamp, event_type, camera_id, zone_id, dwell_ms
            FROM events
            WHERE {event_filter}
            ORDER BY visitor_id, timestamp
        """, params)
        
        events_by_visitor = {}
        for row in cursor.fetchall():
            vid = row[0]
            events_by_visitor.setdefault(vid, []).append({
                "timestamp": datetime.fromisoformat(row[1]),
                "event_type": row[2],
                "camera_id": row[3],
                "zone_id": row[4],
                "dwell_ms": row[5] or 0
            })
            
        dwell_times = []
        for vid, evs in events_by_visitor.items():
            current_visit = []
            visits = []
            for ev in evs:
                if not current_visit:
                    current_visit.append(ev)
                else:
                    last_ev = current_visit[-1]
                    gap = (ev["timestamp"] - last_ev["timestamp"]).total_seconds()
                    # Split if gap > 15 minutes (900 seconds) OR if the last event was an explicit EXIT
                    is_exit = last_ev["event_type"] in ("EXIT", "exit") or (last_ev["event_type"] in ("ZONE_EXIT", "zone_exited") and last_ev["zone_id"] == "ENTRANCE")
                    if gap > 900 or is_exit:
                        visits.append(current_visit)
                        current_visit = [ev]
                    else:
                        current_visit.append(ev)
            if current_visit:
                visits.append(current_visit)
                
            for visit in visits:
                if len(visit) > 1:
                    v_dwell = (visit[-1]["timestamp"] - visit[0]["timestamp"]).total_seconds()
                    if v_dwell > 0:
                        dwell_times.append(v_dwell)
                elif len(visit) == 1:
                    v_dwell = visit[0]["dwell_ms"] / 1000.0
                    if v_dwell > 0:
                        dwell_times.append(v_dwell)

        avg_dwell_minutes = round((sum(dwell_times) / len(dwell_times) / 60.0) if dwell_times else 0.0, 1)

        # Calculate conversion rate
        conversion_rate = round((transactions / visitors * 100) if visitors > 0 else 0.0, 2)

        # Zone-wise metrics (traffic per zone, excluding staff)
        cursor.execute(f"""
            SELECT zone_id, COUNT(DISTINCT visitor_id)
            FROM events
            WHERE {event_filter} AND zone_id IS NOT NULL
            GROUP BY zone_id
        """, params)
        zone_traffic = {row[0]: row[1] for row in cursor.fetchall()}

        # Average dwell per zone (using dwell_ms column from ZONE_EXIT events, excluding staff)
        cursor.execute(f"""
            SELECT zone_id, AVG(dwell_ms)
            FROM events
            WHERE {event_filter} AND event_type = 'ZONE_EXIT' AND zone_id IS NOT NULL AND dwell_ms > 0
            GROUP BY zone_id
        """, params)
        zone_dwells = {row[0]: round((row[1] or 0.0) / 1000.0, 1) for row in cursor.fetchall()} # in seconds

        # Queue Depth (active visitors in queue zone, excluding staff)
        cursor.execute(f"""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE {event_filter} AND event_type = 'BILLING_QUEUE_JOIN'
            AND visitor_id NOT IN (
                SELECT DISTINCT visitor_id FROM events
                WHERE {event_filter} AND event_type IN ('BILLING_QUEUE_ABANDON', 'ZONE_EXIT') AND zone_id LIKE '%BILLING%'
            )
        """, params + params)
        queue_depth = cursor.fetchone()[0] or 0

        # Queue Abandonment Rate (excluding staff)
        cursor.execute(f"SELECT COUNT(DISTINCT visitor_id) FROM events WHERE {event_filter} AND event_type = 'BILLING_QUEUE_ABANDON'", params)
        abandons = cursor.fetchone()[0] or 0
        cursor.execute(f"SELECT COUNT(DISTINCT visitor_id) FROM events WHERE {event_filter} AND event_type = 'BILLING_QUEUE_JOIN'", params)
        joins = cursor.fetchone()[0] or 0
        
        abandonment_rate = round((abandons / joins * 100) if joins > 0 else 0.0, 2)

        conn.close()

        # Build zone-wise metrics dictionary mapping zone_id -> avg_dwell
        avg_dwell_per_zone = {}
        for zid in zone_traffic.keys():
            avg_dwell_per_zone[zid] = zone_dwells.get(zid, 0.0)

        return {
            "store_id": store_id,
            "query_date": query_date_str,
            "using_fallback_aggregates": use_fallback,
            "total_visitors": visitors,
            "total_transactions": transactions,
            "conversion_rate_percentage": conversion_rate,
            "average_dwell_minutes": avg_dwell_minutes,
            "total_revenue": revenue,
            "zone_traffic": zone_traffic,
            "avg_dwell_per_zone": avg_dwell_per_zone,
            "queue_depth": queue_depth,
            "abandonment_rate_percentage": abandonment_rate
        }

    def compute_heatmap(self, store_id: str, date: str) -> dict:
        """
        Computes visitor density heatmap data for layout zones.
        Returns visits, average dwells, normalized scores (0-100), and data_confidence flags.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE store_id = ? AND date(timestamp) = ?", (store_id, date))
        event_count = cursor.fetchone()[0]
        use_fallback = (event_count == 0)

        if use_fallback:
            event_filter = "store_id = ? AND is_staff = 0"
            params = (store_id,)
        else:
            event_filter = "store_id = ? AND date(timestamp) = ? AND is_staff = 0"
            params = (store_id, date)

        # Query frequency and average dwell per zone
        cursor.execute(f"""
            SELECT zone_id, COUNT(DISTINCT visitor_id), AVG(dwell_ms)
            FROM events
            WHERE {event_filter} AND zone_id IS NOT NULL
            GROUP BY zone_id
        """, params)
        
        rows = cursor.fetchall()
        conn.close()

        zones_data = {}
        max_visits = 0
        
        for row in rows:
            zone_id, visits, avg_dwell_ms = row
            zones_data[zone_id] = {
                "visits": visits,
                "avg_dwell_seconds": round((avg_dwell_ms or 0.0) / 1000.0, 1)
            }
            if visits > max_visits:
                max_visits = visits

        # Normalize 0-100 and format
        heatmap_data = []
        for zone_id, data in zones_data.items():
            visits = data["visits"]
            norm_val = round((visits / max_visits * 100) if max_visits > 0 else 0.0, 1)
            heatmap_data.append({
                "zone_id": zone_id,
                "visit_frequency": visits,
                "avg_dwell_seconds": data["avg_dwell_seconds"],
                "normalized_density": norm_val
            })

        # data_confidence flag
        data_confidence = len(heatmap_data) > 0 and max_visits >= 3

        return {
            "store_id": store_id,
            "query_date": date,
            "using_fallback_aggregates": use_fallback,
            "heatmap": heatmap_data,
            "data_confidence": data_confidence
        }
