# pipeline/emit.py
"""
Event schema definition and event emission utility.
Converts tracking events (ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL, BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY) 
into standard JSON payloads and emits them to the ingestion backend.
"""
import json
import requests
from datetime import datetime

class EventEmitter:
    def __init__(self, backend_url: str = "http://localhost:8000"):
        self.backend_url = backend_url

    def emit_event(self, event_data: dict, to_api: bool = False):
        """
        Emits an event either to the FastAPI backend or logs it locally.
        """
        print(f"Emitting event: {event_data.get('event_type')} for visitor {event_data.get('visitor_id') or event_data.get('id_token') or event_data.get('track_id')}")
        if to_api:
            try:
                # Post to the batch endpoint as a list containing the single event
                res = requests.post(f"{self.backend_url}/events/ingest", json=[event_data], timeout=5)
                return res.status_code == 200
            except Exception as e:
                print(f"Failed to send event to API: {e}")
                return False
        else:
            # Write to a local events file (append mode)
            with open("emitted_events.jsonl", "a") as f:
                f.write(json.dumps(event_data) + "\n")
            return True
