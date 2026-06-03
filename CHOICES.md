# Architecture Choices & Reasoning (CHOICES.md)

This document details the key technical decisions made during the design and implementation of the Purplle Store Intelligence System, comparing alternatives, AI recommendations, and final choices.

---

## 💡 Choice 1: YOLOv8 + Custom Python Centroid/IoU Tracker
* **Requirement:** Trace visitor bounding boxes across consecutive video frames.
* **Alternatives Considered:**
  1. **ByteTrack / DeepSORT:** Highly accurate multi-object trackers (MOT) written in C++/Cython.
  2. **Raw Centroid Tracker:** Simple distance-only tracker.
* **AI Suggestions:**
  - AI suggested raw centroid tracking for ease of cross-platform setup, but warned that identity switching would ruin checkout queue and conversion funnel statistics in crowded store layouts.
  - AI suggested ByteTrack, but noted that compiling platform-specific bindings frequently fails on target evaluation platforms (especially Windows) without local C++ compilers.
* **Final Choice:** A hybrid **Custom Centroid & IoU Tracker** written in pure Python/NumPy.
* **Reasoning:** Enforcing a minimum bounding box Intersection-over-Union (IoU) of `0.15` prevents identity switches when paths cross. Configuring a disappearance buffer of `45` frames maintains visitor ID integrity during visual occlusions. Pure Python/NumPy ensures immediate, zero-compilation execution on Windows, macOS, and Linux.

---

## 💾 Choice 2: Event Schema Design (Visitor Session Centric)
* **Requirement:** Design a scalable event schema capable of capturing store entry, exit, zone transitions, dwell times, and queue details.
* **Alternatives Considered:**
  1. **Raw Coordinates Stream:** Sending coordinates of every frame to the server for processing.
  2. **Flat Relational Event Schema:** Sending discrete events with flat metadata values.
  3. **Aggregated JSON Payload Schema:** Exposing standard fields with a nested `metadata` field.
* **AI Suggestions:**
  - AI recommended a flexible schema with a generic `metadata` JSON field to separate core tracking coordinates from context-specific attributes (e.g., age predictions, group properties, wait times).
  - AI advised against a raw coordinate stream because server-side polygon mapping for hundreds of active camera feeds leads to CPU bottlenecks.
* **Final Choice:** **Aggregated JSON Payload Schema** using Pydantic models.
* **Reasoning:** Standardized fields like `event_id`, `visitor_id`, and `timestamp` allow fast indexing and deduplication. The nested `metadata` dictionary preserves system scalability, enabling edge processors to emit predictors (age/gender/group sizes) without modifying database tables or API definitions.

---

## 🔌 Choice 3: API Framework & SQLite Database Architecture
* **Requirement:** Ingest streaming CCTV events in real-time and calculate store performance indicators (conversion, funnel, anomalies).
* **Alternatives Considered:**
  1. **Flask with PostgreSQL:** Standard WSGI backend with dedicated database server.
  2. **FastAPI with SQLite:** High-performance ASGI framework with local file-based database.
* **AI Suggestions:**
  - AI suggested FastAPI due to its native asynchronous support, Pydantic data validation out of the box, and auto-generated Swagger documentation.
  - AI recommended SQLite for local evaluations because it requires zero manual setup (no ports, passwords, or background services).
* **Final Choice:** **FastAPI and SQLite with DB-Level Deduplication Constraints.**
* **Reasoning:** FastAPI handles parallel POST requests from multiple camera feeds efficiently. SQLite is built into Python, eliminating database installation friction. Placing a unique constraint on `event_id` in SQLite implements an idempotent "ON CONFLICT IGNORE" check, filtering duplicate retry logs directly at the database level.
