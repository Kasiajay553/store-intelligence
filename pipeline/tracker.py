# pipeline/tracker.py
"""
Centroid and IoU tracking module.
Provides robust tracking of detected bounding boxes across consecutive video frames
without requiring external compile-heavy binaries.
"""
import numpy as np

class CentroidTracker:
    def __init__(self, max_disappeared=30, min_iou=0.1):
        self.next_object_id = 100  # Start track IDs at 100
        self.objects = {}         # id -> centroid (x, y)
        self.bboxes = {}          # id -> bbox [x1, y1, x2, y2]
        self.disappeared = {}     # id -> frames disappeared count
        self.max_disappeared = max_disappeared
        self.min_iou = min_iou

    def register(self, bbox, centroid):
        self.objects[self.next_object_id] = centroid
        self.bboxes[self.next_object_id] = bbox
        self.disappeared[self.next_object_id] = 0
        self.next_object_id += 1

    def deregister(self, object_id):
        del self.objects[object_id]
        del self.bboxes[object_id]
        del self.disappeared[object_id]

    def _compute_iou(self, boxA, boxB):
        # Calculate intersection over union
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

        iou = interArea / float(boxAArea + boxBArea - interArea + 1e-6)
        return iou

    def update(self, rects):
        """
        rects: list of bounding boxes [x1, y1, x2, y2]
        Returns: dict of active tracked objects {id: (bbox, centroid)}
        """
        if len(rects) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            return {oid: (self.bboxes[oid], self.objects[oid]) for oid in self.objects}

        input_centroids = np.zeros((len(rects), 2), dtype="int")
        for i, (startX, startY, endX, endY) in enumerate(rects):
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            input_centroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(len(rects)):
                self.register(rects[i], input_centroids[i])
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())

            # Distance matrix between active tracks and input centroids
            D = np.linalg.norm(np.array(object_centroids)[:, np.newaxis] - input_centroids, axis=2)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue

                object_id = object_ids[row]
                
                # Check bounding box IoU constraint
                if self._compute_iou(self.bboxes[object_id], rects[col]) < self.min_iou:
                    continue

                self.objects[object_id] = input_centroids[col]
                self.bboxes[object_id] = rects[col]
                self.disappeared[object_id] = 0

                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(len(object_centroids))).difference(used_rows)
            unused_cols = set(range(len(input_centroids))).difference(used_cols)

            for row in unused_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)

            for col in unused_cols:
                self.register(rects[col], input_centroids[col])

        return {oid: (self.bboxes[oid], self.objects[oid]) for oid in self.objects}
