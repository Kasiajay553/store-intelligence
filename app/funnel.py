# app/funnel.py
"""
Funnel computation engine.
Calculates how visitors flow from entry, browsing shelves, queueing, and checking out.
Enforces session-based aggregation and re-entry deduplication.
"""
import sqlite3
from datetime import datetime

class FunnelEngine:
    def __init__(self, db_path: str = "store_intelligence.db"):
        self.db_path = db_path

    def compute_funnel(self, store_id: str, date: str) -> dict:
        """
        Computes the retail funnel stages for a store on a given date.
        Funnel Path: Entry -> Zone Visit (Product Browse) -> Billing Queue -> Purchase
        Excludes staff and deduplicates re-entries.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check date presence in events
        cursor.execute("SELECT COUNT(*) FROM events WHERE store_id = ? AND date(timestamp) = ?", (store_id, date))
        event_count = cursor.fetchone()[0]
        use_fallback = (event_count == 0)

        # Base filters
        if use_fallback:
            event_filter = "store_id = ? AND is_staff = 0"
            tx_filter = "store_id = ?"
            params = (store_id,)
        else:
            event_filter = "store_id = ? AND date(timestamp) = ? AND is_staff = 0"
            tx_filter = "store_id = ? AND date(order_timestamp) = ?"
            params = (store_id, date)

        # Stage 1: Store entry (all unique visitor_ids who triggered ENTRY or any event)
        cursor.execute(f"SELECT DISTINCT visitor_id FROM events WHERE {event_filter}", params)
        entry_visitors = {row[0] for row in cursor.fetchall() if row[0] is not None}
        count_stage_1 = len(entry_visitors)

        # Stage 2: Zone Visit / Product browsing (visited shelf or display)
        # Find unique visitor_ids who entered any zone that starts with PURPLLE_ or has Z in it, excluding entrances and billing
        cursor.execute(f"""
            SELECT DISTINCT visitor_id 
            FROM events 
            WHERE {event_filter} AND event_type = 'ZONE_ENTER' 
            AND zone_id IS NOT NULL 
            AND zone_id NOT LIKE '%BILLING%' 
            AND zone_id NOT LIKE '%ENTRY%'
        """, params)
        browse_visitors = {row[0] for row in cursor.fetchall() if row[0] is not None}
        # Deduplicate & intersect with entry
        count_stage_2 = len(browse_visitors.intersection(entry_visitors))

        # Stage 3: Joined checkout queue (BILLING_QUEUE_JOIN or entering BILLING zone)
        cursor.execute(f"""
            SELECT DISTINCT visitor_id 
            FROM events 
            WHERE {event_filter} AND (event_type = 'BILLING_QUEUE_JOIN' OR (event_type = 'ZONE_ENTER' AND zone_id LIKE '%BILLING%'))
        """, params)
        queue_visitors = {row[0] for row in cursor.fetchall() if row[0] is not None}
        count_stage_3 = len(queue_visitors.intersection(entry_visitors))

        # Stage 4: Checkout transaction (POS conversion)
        cursor.execute(f"SELECT COUNT(DISTINCT order_id) FROM transactions WHERE {tx_filter}", params)
        count_stage_4 = cursor.fetchone()[0] or 0

        # Enforce non-increasing bounds (Stage N <= Stage N-1)
        if count_stage_2 > count_stage_1:
            count_stage_2 = count_stage_1
        if count_stage_3 > count_stage_2:
            count_stage_3 = count_stage_2
        if count_stage_4 > count_stage_3:
            count_stage_4 = count_stage_3

        # Percentages
        pct_1 = 100.0
        pct_2 = round((count_stage_2 / count_stage_1 * 100) if count_stage_1 > 0 else 0.0, 1)
        pct_3 = round((count_stage_3 / count_stage_1 * 100) if count_stage_1 > 0 else 0.0, 1)
        pct_4 = round((count_stage_4 / count_stage_1 * 100) if count_stage_1 > 0 else 0.0, 1)

        conn.close()

        return {
            "store_id": store_id,
            "query_date": date,
            "using_fallback_aggregates": use_fallback,
            "stages": [
                {"stage": "1_Entry", "count": count_stage_1, "percentage": pct_1},
                {"stage": "2_Product_Browse", "count": count_stage_2, "percentage": pct_2},
                {"stage": "3_Billing_Queue", "count": count_stage_3, "percentage": pct_3},
                {"stage": "4_Checkout_Complete", "count": count_stage_4, "percentage": pct_4}
            ],
            "drop_offs": {
                "entrance_to_browsing": max(0, count_stage_1 - count_stage_2),
                "browsing_to_queue": max(0, count_stage_2 - count_stage_3),
                "queue_to_checkout": max(0, count_stage_3 - count_stage_4)
            }
        }
