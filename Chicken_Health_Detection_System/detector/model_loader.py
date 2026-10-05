# """
# model_loader.py
# ------------------
# All the YOLO detection logic lives here, kept separate from views.py so the
# model is loaded ONCE (singleton) and reused across every request instead of
# reloading weights from disk each time — this matters a lot for response speed.

# Three entry points, one per mode on the website:
#     - detect_image()          -> single uploaded photo
#     - process_video()         -> uploaded CCTV/recorded video file
#     - generate_live_frames()  -> live webcam or CCTV (RTSP) stream
# """

# import time
# from collections import deque, defaultdict

# import cv2
# from django.conf import settings
# from ultralytics import YOLO

# _model = None  # module-level singleton


# def get_model():
#     """Loads the YOLO model once and reuses it for every request afterwards."""
#     global _model
#     if _model is None:
#         print(f"[INFO] Loading YOLO model from: {settings.MODEL_WEIGHTS_PATH}")
#         _model = YOLO(settings.MODEL_WEIGHTS_PATH)
#     return _model


# def classify_names(names_dict):
#     """Splits the model's class ids into sick-like / healthy-like sets by
#     matching substrings, so it works regardless of exact class naming."""
#     sick_ids, healthy_ids = set(), set()
#     for cls_id, name in names_dict.items():
#         lname = name.lower()
#         if "sick" in lname or "diseased" in lname:
#             sick_ids.add(cls_id)
#         elif "health" in lname:
#             healthy_ids.add(cls_id)
#     return sick_ids, healthy_ids


# # ---------------------------------------------------------------------------
# # MODE 1: Single image upload
# # ---------------------------------------------------------------------------
# def detect_image(image_path, output_path, conf_thresh=None):
#     """Runs detection on one image, draws boxes, saves an annotated copy.
#     Returns a summary dict used by the results page."""
#     conf_thresh = conf_thresh or settings.DETECTION_CONF_THRESHOLD
#     model = get_model()
#     sick_ids, healthy_ids = classify_names(model.names)

#     frame = cv2.imread(image_path)
#     if frame is None:
#         raise ValueError(f"Could not read image: {image_path}")

#     results = model.predict(frame, conf=conf_thresh, verbose=False)[0]

#     detections = []
#     healthy_count = 0
#     sick_count = 0

#     for box in results.boxes:
#         cls_id = int(box.cls[0])
#         conf = float(box.conf[0])
#         x1, y1, x2, y2 = map(int, box.xyxy[0])
#         label = model.names[cls_id]

#         if cls_id in sick_ids:
#             color = (0, 0, 255)
#             sick_count += 1
#         elif cls_id in healthy_ids:
#             color = (0, 200, 0)
#             healthy_count += 1
#         else:
#             color = (0, 200, 200)

#         cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
#         cv2.putText(frame, f"{label} {conf:.2f}", (x1, max(y1 - 8, 0)),
#                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

#         detections.append({
#             "label": label,
#             "confidence": round(conf, 3),
#             "box": [x1, y1, x2, y2],
#         })

#     cv2.imwrite(output_path, frame)

#     return {
#         "total_detections": len(detections),
#         "healthy_count": healthy_count,
#         "sick_count": sick_count,
#         "detections": detections,
#     }


# # ---------------------------------------------------------------------------
# # MODE 2: Uploaded CCTV / recorded video file
# # ---------------------------------------------------------------------------
# def process_video(video_path, output_path, conf_thresh=None,
#                    sick_time_window_sec=120, sick_ratio_threshold=0.75,
#                    min_track_len=15):
#     """Runs tracked detection across the whole video, saves an annotated
#     output video, and returns a summary. Same tracking + sustained-sick
#     approach discussed for CCTV footage: a bird is only counted as
#     "sustained sick" if it stayed classified Sick across a rolling window,
#     not from one flickering frame."""
#     conf_thresh = conf_thresh or settings.DETECTION_CONF_THRESHOLD
#     model = get_model()
#     sick_ids, healthy_ids = classify_names(model.names)

#     probe = cv2.VideoCapture(video_path)
#     fps = probe.get(cv2.CAP_PROP_FPS) or 25.0
#     width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
#     height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
#     probe.release()

#     fourcc = cv2.VideoWriter_fourcc(*"mp4v")
#     writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

#     history = defaultdict(deque)
#     all_ids_seen = set()
#     sick_flagged_ids = set()

#     frame_idx = 0
#     for result in model.track(source=video_path, conf=conf_thresh, persist=True,
#                                tracker="bytetrack.yaml", stream=True, verbose=False):
#         frame = result.orig_img
#         video_time = frame_idx / fps

#         if result.boxes.id is not None:
#             for box, track_id in zip(result.boxes, result.boxes.id):
#                 track_id = int(track_id)
#                 all_ids_seen.add(track_id)
#                 cls_id = int(box.cls[0])
#                 x1, y1, x2, y2 = map(int, box.xyxy[0])
#                 label = model.names[cls_id]
#                 is_sick = cls_id in sick_ids

#                 hist = history[track_id]
#                 hist.append((video_time, is_sick))
#                 while hist and video_time - hist[0][0] > sick_time_window_sec:
#                     hist.popleft()
#                 sick_ratio = sum(1 for _, s in hist if s) / len(hist)

#                 color = (0, 0, 255) if is_sick else (0, 200, 0)
#                 cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
#                 cv2.putText(frame, f"ID{track_id} {label}", (x1, max(y1 - 8, 0)),
#                             cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

#                 if len(hist) >= min_track_len and sick_ratio >= sick_ratio_threshold:
#                     sick_flagged_ids.add(track_id)

#         writer.write(frame)
#         frame_idx += 1

#     writer.release()

#     return {
#         "total_frames": frame_idx,
#         "unique_chickens_tracked": len(all_ids_seen),
#         "sustained_sick_count": len(sick_flagged_ids),
#     }


# # ---------------------------------------------------------------------------
# # MODE 3: Live webcam / CCTV (RTSP) stream
# # ---------------------------------------------------------------------------
# def generate_live_frames(source, conf_thresh=None):
#     """Generator that yields MJPEG-encoded JPEG frames with boxes drawn, for
#     the browser to display as a live <img> stream. `source` is either a
#     webcam index (e.g. "0") or an RTSP/HTTP camera URL."""
#     conf_thresh = conf_thresh or settings.DETECTION_CONF_THRESHOLD
#     model = get_model()
#     sick_ids, healthy_ids = classify_names(model.names)

#     cap_source = int(source) if str(source).isdigit() else source

#     for result in model.track(source=cap_source, conf=conf_thresh, persist=True,
#                                tracker="bytetrack.yaml", stream=True, verbose=False):
#         frame = result.orig_img
#         healthy_count = 0
#         sick_count = 0

#         if result.boxes.id is not None:
#             for box, track_id in zip(result.boxes, result.boxes.id):
#                 track_id = int(track_id)
#                 cls_id = int(box.cls[0])
#                 x1, y1, x2, y2 = map(int, box.xyxy[0])
#                 label = model.names[cls_id]
#                 is_sick = cls_id in sick_ids

#                 if is_sick:
#                     sick_count += 1
#                     color = (0, 0, 255)
#                 else:
#                     healthy_count += 1
#                     color = (0, 200, 0)

#                 cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
#                 cv2.putText(frame, f"ID{track_id} {label}", (x1, max(y1 - 8, 0)),
#                             cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

#         cv2.putText(frame, f"Healthy: {healthy_count}   Sick: {sick_count}",
#                     (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

#         ok, buffer = cv2.imencode(".jpg", frame)
#         if not ok:
#             continue

#         yield (b"--frame\r\n"
#                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")


"""
model_loader.py
------------------
All the YOLO detection logic lives here, kept separate from views.py so the
model is loaded ONCE (singleton) and reused across every request instead of
reloading weights from disk each time — this matters a lot for response speed.

Three entry points, one per mode on the website:
    - detect_image()          -> single uploaded photo
    - process_video()         -> uploaded CCTV/recorded video file
    - generate_live_frames()  -> live webcam or CCTV (RTSP) stream
"""

import time
from collections import deque, defaultdict

import cv2
from django.conf import settings
from ultralytics import YOLO

_model = None  # module-level singleton


def get_model():
    """Loads the YOLO model once and reuses it for every request afterwards."""
    global _model
    if _model is None:
        print(f"[INFO] Loading YOLO model from: {settings.MODEL_WEIGHTS_PATH}")
        _model = YOLO(settings.MODEL_WEIGHTS_PATH)
    return _model


def classify_names(names_dict):
    """Splits the model's class ids into sick-like / healthy-like sets by
    matching substrings, so it works regardless of exact class naming."""
    sick_ids, healthy_ids = set(), set()
    for cls_id, name in names_dict.items():
        lname = name.lower()
        if "sick" in lname or "diseased" in lname:
            sick_ids.add(cls_id)
        elif "health" in lname:
            healthy_ids.add(cls_id)
    return sick_ids, healthy_ids


def passes_class_threshold(cls_id, conf, sick_ids, healthy_ids):
    """Applies the PER-CLASS confidence threshold from settings, on top of
    the low MODEL_BASE_CONF the model itself was called with. This is what
    lets 'Sick' require a stricter confidence than 'Healthy' — the model.
    predict()/track() 'conf' argument alone can't do this since it applies
    one global cutoff to every class equally."""
    thresholds = settings.DETECTION_CONF_THRESHOLDS
    if cls_id in sick_ids:
        return conf >= thresholds.get("sick", thresholds["default"])
    elif cls_id in healthy_ids:
        return conf >= thresholds.get("healthy", thresholds["default"])
    return conf >= thresholds["default"]


# ---------------------------------------------------------------------------
# MODE 1: Single image upload
# ---------------------------------------------------------------------------
def detect_image(image_path, output_path, conf_thresh=None):
    """Runs detection on one image, draws boxes, saves an annotated copy.
    Returns a summary dict used by the results page."""
    model = get_model()
    sick_ids, healthy_ids = classify_names(model.names)

    frame = cv2.imread(image_path)
    if frame is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Ask the model for candidates down to the low base floor, THEN filter
    # each one by its own class's threshold below — this is what makes
    # per-class thresholds possible.
    base_conf = conf_thresh or settings.MODEL_BASE_CONF
    results = model.predict(frame, conf=base_conf, verbose=False)[0]

    detections = []
    healthy_count = 0
    sick_count = 0

    for box in results.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])

        if not passes_class_threshold(cls_id, conf, sick_ids, healthy_ids):
            continue  # didn't meet this class's own threshold — discard

        x1, y1, x2, y2 = map(int, box.xyxy[0])
        label = model.names[cls_id]

        if cls_id in sick_ids:
            color = (0, 0, 255)
            sick_count += 1
        elif cls_id in healthy_ids:
            color = (0, 200, 0)
            healthy_count += 1
        else:
            color = (0, 200, 200)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{label} {conf:.2f}", (x1, max(y1 - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        detections.append({
            "label": label,
            "confidence": round(conf, 3),
            "box": [x1, y1, x2, y2],
        })

    cv2.imwrite(output_path, frame)

    return {
        "total_detections": len(detections),
        "healthy_count": healthy_count,
        "sick_count": sick_count,
        "detections": detections,
    }


# ---------------------------------------------------------------------------
# MODE 2: Uploaded CCTV / recorded video file
# ---------------------------------------------------------------------------
def process_video(video_path, output_path, conf_thresh=None,
                   sick_time_window_sec=120, sick_ratio_threshold=0.75,
                   min_track_len=15):
    """Runs tracked detection across the whole video, saves an annotated
    output video, and returns a summary. Same tracking + sustained-sick
    approach discussed for CCTV footage: a bird is only counted as
    "sustained sick" if it stayed classified Sick across a rolling window,
    not from one flickering frame."""
    base_conf = conf_thresh or settings.MODEL_BASE_CONF
    model = get_model()
    sick_ids, healthy_ids = classify_names(model.names)

    probe = cv2.VideoCapture(video_path)
    fps = probe.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    history = defaultdict(deque)
    all_ids_seen = set()
    sick_flagged_ids = set()

    frame_idx = 0
    for result in model.track(source=video_path, conf=base_conf, persist=True,
                               tracker="bytetrack.yaml", stream=True, verbose=False):
        frame = result.orig_img
        video_time = frame_idx / fps

        if result.boxes.id is not None:
            for box, track_id in zip(result.boxes, result.boxes.id):
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if not passes_class_threshold(cls_id, conf, sick_ids, healthy_ids):
                    continue  # below this class's own threshold — skip drawing/counting

                track_id = int(track_id)
                all_ids_seen.add(track_id)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                label = model.names[cls_id]
                is_sick = cls_id in sick_ids

                hist = history[track_id]
                hist.append((video_time, is_sick))
                while hist and video_time - hist[0][0] > sick_time_window_sec:
                    hist.popleft()
                sick_ratio = sum(1 for _, s in hist if s) / len(hist)

                color = (0, 0, 255) if is_sick else (0, 200, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"ID{track_id} {label}", (x1, max(y1 - 8, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                if len(hist) >= min_track_len and sick_ratio >= sick_ratio_threshold:
                    sick_flagged_ids.add(track_id)

        writer.write(frame)
        frame_idx += 1

    writer.release()

    return {
        "total_frames": frame_idx,
        "unique_chickens_tracked": len(all_ids_seen),
        "sustained_sick_count": len(sick_flagged_ids),
    }


# ---------------------------------------------------------------------------
# MODE 3: Live webcam / CCTV (RTSP) stream
# ---------------------------------------------------------------------------
def generate_live_frames(source, conf_thresh=None):
    """Generator that yields MJPEG-encoded JPEG frames with boxes drawn, for
    the browser to display as a live <img> stream. `source` is either a
    webcam index (e.g. "0") or an RTSP/HTTP camera URL."""
    base_conf = conf_thresh or settings.MODEL_BASE_CONF
    model = get_model()
    sick_ids, healthy_ids = classify_names(model.names)

    cap_source = int(source) if str(source).isdigit() else source

    for result in model.track(source=cap_source, conf=base_conf, persist=True,
                               tracker="bytetrack.yaml", stream=True, verbose=False):
        frame = result.orig_img
        healthy_count = 0
        sick_count = 0

        if result.boxes.id is not None:
            for box, track_id in zip(result.boxes, result.boxes.id):
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if not passes_class_threshold(cls_id, conf, sick_ids, healthy_ids):
                    continue  # below this class's own threshold — skip drawing/counting

                track_id = int(track_id)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                label = model.names[cls_id]
                is_sick = cls_id in sick_ids

                if is_sick:
                    sick_count += 1
                    color = (0, 0, 255)
                else:
                    healthy_count += 1
                    color = (0, 200, 0)

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"ID{track_id} {label}", (x1, max(y1 - 8, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        cv2.putText(frame, f"Healthy: {healthy_count}   Sick: {sick_count}",
                    (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            continue

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")