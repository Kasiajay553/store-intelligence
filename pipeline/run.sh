#!/bin/bash
# pipeline/run.sh
# Runs the full video processing pipeline.
# Add --api to post events to the live FastAPI server.

python pipeline/run.py "$@"
