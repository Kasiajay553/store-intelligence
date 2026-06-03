# pipeline/run.py
"""
Orchestration script to process all available CCTV video clips for Store 1 and Store 2,
mapping them to the store layout and emitting events.
"""
import os
import sys
from pipeline.detect import VideoProcessor, load_store_layout

def process_all_clips(to_api=False):
    layout = load_store_layout("store_layout.json")
    
    # 1. Store 1 Clips (Mapping store files)
    store_1_dir = os.path.join("cctv_clips", "Store 1")
    if os.path.exists(store_1_dir):
        print("--- Processing Store 1 CCTV Clips ---")
        # Video files to camera_id mappings
        s1_mappings = {
            "CAM 3 - entry.mp4": "CAM3",       # Entry/Exit Camera
            "CAM 1 - zone.mp4": "CAM1",        # Zone Left Shelf
            "CAM 2 - zone.mp4": "CAM2",        # Zone Center Display
            "CAM 5 - billing.mp4": "CAM5"      # Billing Counter Queue
        }

        for video_file, camera_id in s1_mappings.items():
            video_path = os.path.join(store_1_dir, video_file)
            if os.path.exists(video_path):
                processor = VideoProcessor(store_id="ST1008", camera_id=camera_id, layout_data=layout)
                # Run with frame_step=30 (1 frame per second) for fast execution
                processor.process(video_path, frame_step=30, to_api=to_api)
            else:
                print(f"Clip not found: {video_path}")

    # 2. Store 2 Clips
    store_2_dir = os.path.join("cctv_clips", "Store 2")
    if os.path.exists(store_2_dir):
        print("\n--- Processing Store 2 CCTV Clips ---")
        s2_mappings = {
            "entry 1.mp4": "CAM3",
            "entry 2.mp4": "CAM3",
            "zone.mp4": "CAM2",
            "billing_area.mp4": "CAM5"
        }

        for video_file, camera_id in s2_mappings.items():
            video_path = os.path.join(store_2_dir, video_file)
            if os.path.exists(video_path):
                processor = VideoProcessor(store_id="ST1008", camera_id=camera_id, layout_data=layout)
                processor.process(video_path, frame_step=30, to_api=to_api)
            else:
                print(f"Clip not found: {video_path}")

if __name__ == "__main__":
    to_api = "--api" in sys.argv
    process_all_clips(to_api=to_api)
