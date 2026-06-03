# app/ingestion.py
"""
Complete event ingestion and POS transaction parsing engine.
Manages database creation, deduplication constraints, and importing raw CSV records.
"""
import os
import csv
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Dict, Any
from app.models import EventPayload

class IngestionEngine:
    def __init__(self, db_path: str = "store_intelligence.db"):
        self.db_path = db_path
        self._init_db()
        self._import_pos_csv()

    def _init_db(self):
        """Creates SQLite tables and sets unique constraints for deduplication."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ingestion event store (idempotent by event_id primary key)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                store_id TEXT,
                camera_id TEXT,
                visitor_id TEXT,
                event_type TEXT,
                timestamp TEXT,
                zone_id TEXT,
                dwell_ms INTEGER,
                is_staff INTEGER,
                confidence REAL,
                metadata TEXT
            )
        """)
        
        # POS transactions store
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                order_id INTEGER PRIMARY KEY,
                order_date TEXT,
                order_time TEXT,
                order_timestamp TEXT,
                store_id TEXT,
                product_id TEXT,
                brand_name TEXT,
                total_amount REAL
            )
        """)
        
        conn.commit()
        conn.close()

    def _import_pos_csv(self):
        """Locates the POS transactions CSV file in the workspace and populates the database."""
        csv_file = None
        for file in os.listdir("."):
            if file.startswith("POS - sample transactions") and file.endswith(".csv"):
                csv_file = file
                break

        if not csv_file:
            print("POS transactions CSV file not found in workspace.")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if already imported
        cursor.execute("SELECT COUNT(*) FROM transactions")
        if cursor.fetchone()[0] > 0:
            conn.close()
            return

        print(f"Importing transactions from {csv_file} to database...")
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert Date: '10-04-2026' -> 'YYYY-MM-DD'
                date_parts = row["order_date"].split("-")
                formatted_date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                order_timestamp = f"{formatted_date}T{row['order_time']}"

                cursor.execute("""
                    INSERT OR IGNORE INTO transactions 
                    (order_id, order_date, order_time, order_timestamp, store_id, product_id, brand_name, total_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    int(row["order_id"]),
                    formatted_date,
                    row["order_time"],
                    order_timestamp,
                    row["store_id"],
                    row["product_id"],
                    row["brand_name"],
                    float(row["total_amount"])
                ))
        
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM transactions")
        count = cursor.fetchone()[0]
        conn.close()
        print(f"Successfully imported {count} transactions.")

    def ingest(self, event: EventPayload) -> bool:
        """
        Ingests a verified EventPayload into SQLite.
        Handles deduplication implicitly via primary key on event_id.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        event_id = event.event_id
        store_id = event.store_id
        camera_id = event.camera_id
        visitor_id = event.visitor_id
        event_type = event.event_type
        timestamp = event.timestamp.isoformat()
        zone_id = event.zone_id
        dwell_ms = event.dwell_ms or 0
        is_staff = 1 if event.is_staff else 0
        confidence = event.confidence if event.confidence is not None else 1.0
        metadata_str = json.dumps(event.metadata or {})

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO events 
                (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_str))
            conn.commit()
            success = True
        except Exception as e:
            print(f"Error during SQL insertion: {e}")
            success = False
        finally:
            conn.close()

        return success

    def ingest_batch(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ingests a list of raw event dicts with partial success handling.
        Returns a structured dictionary of successes, failures, and errors.
        """
        successful_count = 0
        failed_count = 0
        errors = []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for idx, event_data in enumerate(events):
            try:
                # 1. Validate using EventPayload model
                event = EventPayload(**event_data)
                
                # 2. Extract values
                event_id = event.event_id
                store_id = event.store_id
                camera_id = event.camera_id
                visitor_id = event.visitor_id
                event_type = event.event_type
                timestamp = event.timestamp.isoformat()
                zone_id = event.zone_id
                dwell_ms = event.dwell_ms or 0
                is_staff = 1 if event.is_staff else 0
                confidence = event.confidence if event.confidence is not None else 1.0
                metadata_str = json.dumps(event.metadata or {})
                
                cursor.execute("""
                    INSERT OR IGNORE INTO events 
                    (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_str))
                
                successful_count += 1
            except Exception as e:
                failed_count += 1
                errors.append({
                    "index": idx,
                    "error": str(e)
                })
        
        conn.commit()
        conn.close()
        
        return {
            "successful_count": successful_count,
            "failed_count": failed_count,
            "errors": errors
        }

    def ingest_raw_json(self, raw_event_str: str) -> bool:
        """
        Direct raw JSON line ingestion for loading event logs (.jsonl).
        Maps old event schemas to the new compliant schema model.
        """
        try:
            data = json.loads(raw_event_str)
            
            # Map old keys to new schema
            mapped_data = {}
            
            # 1. Event ID
            if "event_id" in data:
                mapped_data["event_id"] = data["event_id"]
            elif "queue_event_id" in data:
                mapped_data["event_id"] = data["queue_event_id"]
            else:
                # Generate unique hash for event_id
                unique_str = f"{data.get('event_type')}_{data.get('id_token') or data.get('track_id')}_{data.get('store_code') or data.get('store_id')}_{data.get('event_timestamp') or data.get('event_time')}"
                mapped_data["event_id"] = hashlib.md5(unique_str.encode()).hexdigest()
                
            # 2. Store ID
            store_id = data.get("store_id") or data.get("store_code") or "ST1008"
            if store_id == "store_1076":
                store_id = "ST1076"
            mapped_data["store_id"] = store_id
            
            # 3. Camera ID
            mapped_data["camera_id"] = data.get("camera_id") or "CAM3"
            
            # 4. Visitor ID
            visitor_id = data.get("visitor_id")
            if not visitor_id:
                track_id = data.get("track_id")
                id_token = data.get("id_token")
                if id_token:
                    visitor_id = id_token
                elif track_id is not None:
                    visitor_id = f"ID_{track_id}"
                else:
                    visitor_id = "ID_UNKNOWN"
            mapped_data["visitor_id"] = visitor_id
            
            # 5. Event Type (map to uppercase required events)
            etype = (data.get("event_type") or "ENTRY").upper()
            if etype == "ENTRY":
                mapped_data["event_type"] = "ENTRY"
            elif etype == "EXIT":
                mapped_data["event_type"] = "EXIT"
            elif etype == "ZONE_ENTERED":
                mapped_data["event_type"] = "ZONE_ENTER"
            elif etype == "ZONE_EXITED":
                mapped_data["event_type"] = "ZONE_EXIT"
            elif etype == "QUEUE_COMPLETED":
                mapped_data["event_type"] = "ZONE_EXIT"
            elif etype == "QUEUE_ABANDONED":
                mapped_data["event_type"] = "BILLING_QUEUE_ABANDON"
            else:
                mapped_data["event_type"] = etype
                
            # 6. Timestamp mapping
            ts_str = data.get("timestamp") or data.get("event_time") or data.get("event_timestamp") or data.get("queue_join_ts") or datetime.now().isoformat()
            if isinstance(ts_str, str):
                ts_str = ts_str.replace("Z", "")
            mapped_data["timestamp"] = ts_str
            
            # 7. Zone ID
            mapped_data["zone_id"] = data.get("zone_id")
            
            # 8. Dwell MS
            dwell = data.get("dwell_ms")
            if dwell is None:
                wait_sec = data.get("wait_seconds")
                if wait_sec is not None:
                    dwell = int(wait_sec) * 1000
                else:
                    dwell = 0
            mapped_data["dwell_ms"] = dwell
            
            # 9. Is Staff
            mapped_data["is_staff"] = data.get("is_staff", False)
            
            # 10. Confidence
            mapped_data["confidence"] = data.get("confidence", 1.0)
            
            # 11. Metadata
            meta = data.get("metadata") or {}
            for k, v in data.items():
                if k not in ["event_id", "queue_event_id", "store_id", "store_code", "camera_id", "visitor_id", "id_token", "track_id", "event_type", "timestamp", "event_time", "event_timestamp", "zone_id", "dwell_ms", "is_staff", "confidence", "metadata"]:
                    meta[k] = v
            mapped_data["metadata"] = meta
            
            # If queue_completed or queue_abandoned, we also synthesize a BILLING_QUEUE_JOIN event
            if etype in ("QUEUE_COMPLETED", "QUEUE_ABANDONED"):
                join_time = data.get("queue_join_ts")
                if join_time:
                    join_uid = hashlib.md5(f"JOIN_{mapped_data['visitor_id']}_{join_time}".encode()).hexdigest()
                    join_event = EventPayload(
                        event_id=join_uid,
                        store_id=mapped_data["store_id"],
                        camera_id=mapped_data["camera_id"],
                        visitor_id=mapped_data["visitor_id"],
                        event_type="BILLING_QUEUE_JOIN",
                        timestamp=datetime.fromisoformat(join_time),
                        zone_id=mapped_data["zone_id"],
                        dwell_ms=0,
                        is_staff=mapped_data["is_staff"],
                        confidence=mapped_data["confidence"],
                        metadata={"queue_position_at_join": data.get("queue_position_at_join")}
                    )
                    self.ingest(join_event)

            event = EventPayload(**mapped_data)
            return self.ingest(event)
        except Exception as e:
            print(f"Failed to ingest raw json line: {e}")
            return False
