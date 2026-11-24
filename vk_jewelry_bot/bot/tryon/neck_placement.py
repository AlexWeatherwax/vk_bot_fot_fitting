"""Measure exposed neck skin in a chin-relative frame, without model I/O.

The body-skin mask is supplied by the existing multiclass segmenter. Shoulder
width and image centering do not determine neck width or horizontal position.
When skin is hidden or ambiguous, return an explicitly marked face fallback.
"""
from dataclasses import dataclass, replace
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class NeckPlacement:
    center: tuple[float, float]
    top: tuple[float, float]
    base: tuple[float, float]
    width: float
    down: tuple[float, float]
    measured: bool
    upper_measured: bool = False

    @property
    def top_center(self):
        return self.top

    @property
    def base_center(self):
        return self.base

    @property
    def upper_top(self):
        return self.top if self.upper_measured else None

    @property
    def left(self):
        return (self.top[0] - self.down[1] * self.width / 2,
                self.top[1] + self.down[0] * self.width / 2)

    @property
    def right(self):
        return (self.top[0] + self.down[1] * self.width / 2,
                self.top[1] - self.down[0] * self.width / 2)


def _frame(face, pose):
    chin = np.asarray(face.chin, dtype=float)
    forehead = np.asarray(face.forehead_top, dtype=float)
    width = float(face.face_width)
    down = chin - forehead
    length = float(np.linalg.norm(down))
    if (chin.shape != (2,) or forehead.shape != (2,)
            or not np.isfinite(chin).all() or not np.isfinite(forehead).all()
            or not math.isfinite(width) or width < 20 or length < 20):
        raise ValueError("A finite face frame is required for neck placement")
    down /= length
    candidate = np.asarray(getattr(pose, "down", down), dtype=float)
    norm = float(np.linalg.norm(candidate))
    if (candidate.shape == (2,) and np.isfinite(candidate).all() and norm > .1
            and np.dot(candidate / norm, down) >= .8):
        down = candidate / norm
    lateral = np.array([down[1], -down[0]])
    return chin, down, lateral, width


def _placement(chin, down, lateral, face_width, left, right, top, base, measured):
    center = (left + right) / 2
    def point(y):
        xy = chin + lateral * (center * face_width) + down * (y * face_width)
        return tuple(map(float, xy))
    return NeckPlacement(point((top + base) / 2), point(top), point(base),
                         float((right - left) * face_width), tuple(map(float, down)), measured)


def fallback_neck(face, pose=None) -> NeckPlacement:
    """Use the face axis, never the image or shoulder midpoint, if neck is hidden."""
    chin, down, lateral, width = _frame(face, pose)
    base = .38
    if pose is not None and hasattr(pose, "neck_point"):
        point = np.asarray(pose.neck_point, dtype=float)
        if point.shape == (2,) and np.isfinite(point).all():
            distance = float(np.dot(point - chin, down) / width)
            if .15 <= distance <= .75:
                base = distance
    return _placement(chin, down, lateral, width, -.31, .31, .04, base, False)


def _upper_neck_band(body, labels, label, origin_x, origin_y, unit):
    """Locate the two skin wings beside the jaw, connected to this neck below."""
    rows = {}
    for y in range(int(origin_y - unit * .25), int(origin_y - unit * .015)):
        xs = np.flatnonzero((labels[y] == label) & body[y])
        if not len(xs):
            continue
        left = xs[xs < origin_x - unit * .18]
        right = xs[xs > origin_x + unit * .18]
        if len(left) < unit * .025 or len(right) < unit * .025:
            continue
        center = body[y, int(origin_x - unit * .10):int(origin_x + unit * .10)]
        if center.mean() > .30:
            continue
        lo, hi = float(left[0]), float(right[-1] + 1)
        if (not unit * .50 <= hi - lo <= unit * 1.15
                or abs((lo + hi) / 2 - origin_x) > unit * .30):
            continue
        rows[y] = (lo, hi)
    for start in sorted(rows):
        levels = [y for y in range(start, start + 8) if y in rows]
        if len(levels) < 6:
            continue
        bounds = np.array([rows[y] for y in levels])
        widths = bounds[:, 1] - bounds[:, 0]
        centers = bounds.mean(axis=1)
        if np.ptp(widths) > np.median(widths) * .20 or np.ptp(centers) > unit * .10:
            continue
        left, right = np.median(bounds, axis=0)
        return float(left), float(right), float(np.median(levels))
    return None


def _center_at_pose_level(placement, pose):
    if pose is None or not hasattr(pose, 'neck_point') or placement.down[1] <= .2:
        return placement
    target_y = float(pose.neck_point[1])
    if not math.isfinite(target_y):
        return placement
    # Continue the skin-derived neck axis to the existing vertical anchor. This
    # corrects horizontal shoulder bias without changing saved vertical fitting.
    distance = (target_y - placement.center[1]) / placement.down[1]
    if abs(distance) > placement.width:
        return placement
    center = (placement.center[0] + placement.down[0] * distance, target_y)
    return replace(placement, center=center)


def locate_neck(body_skin, face, pose=None, *, face_skin=None) -> NeckPlacement:
    """Trace a stable skin band below this face, stopping at collar or torso flare.

    The normalized grid bounds work independently of upload size. A component
    must reach the area directly under the chin, contain several consistent
    cross-sections, and retain both visible lateral edges. Other arms, people,
    exposed chest and isolated confident pixels cannot establish neck width.
    """
    chin, down, lateral, width = _frame(face, pose)
    fallback = fallback_neck(face, pose)
    confidence = np.asarray(body_skin, dtype=np.float32)
    if (confidence.ndim != 2 or min(confidence.shape) < 5
            or not np.isfinite(confidence).all()):
        return fallback
    body_confidence = confidence.copy()
    if face_skin is not None:
        facial = np.asarray(face_skin, dtype=np.float32)
        if facial.shape == confidence.shape and np.isfinite(facial).all():
            confidence = np.clip(confidence + facial, 0, 1)
    unit, origin_x, origin_y = 200., 240., 80.
    scale = unit / width
    transform = np.array([
        [lateral[0] * scale, lateral[1] * scale, origin_x - np.dot(lateral, chin) * scale],
        [down[0] * scale, down[1] * scale, origin_y - np.dot(down, chin) * scale],
    ])
    upright = cv2.warpAffine(confidence, transform, (480, 340), flags=cv2.INTER_LINEAR)
    upright_body = cv2.warpAffine(body_confidence, transform, (480, 340), flags=cv2.INTER_LINEAR)
    binary = (upright >= .55).astype(np.uint8)
    binary[:int(origin_y - unit * .32)] = 0
    # Thin existing chains can split skin into adjacent regions. Close small
    # horizontal gaps without bridging a shirt collar vertically.
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    body_binary = cv2.morphologyEx((upright_body >= .55).astype(np.uint8),
                                   cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    candidates = []
    min_row, max_row = int(origin_y + unit * .02), int(origin_y + unit * .95)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < unit * unit * .025:
            continue
        rows = {}
        for y in range(min_row, max_row):
            xs = np.flatnonzero(labels[y] == label)
            if not len(xs):
                continue
            # A split by clothes or an intervening hand is not one cross-section.
            splits = np.flatnonzero(np.diff(xs) > 1) + 1
            runs = np.split(xs, splits)
            usable = [run for run in runs
                      if unit * .28 <= len(run) <= unit * 1.08
                      and abs((run[0] + run[-1]) / 2 - origin_x) <= unit * .36]
            if not usable:
                continue
            run = min(usable, key=lambda r: abs((r[0] + r[-1]) / 2 - origin_x))
            rows[y] = (float(run[0]), float(run[-1] + 1))
        # Look for a stable upper-neck band, rather than an isolated narrow run
        # at the jaw tip or a broad chest/arm component farther below the face.
        for start in range(min_row, int(origin_y + unit * .18)):
            window = [rows[y] for y in range(start, start + 20) if y in rows]
            if len(window) < 17:
                continue
            bounds = np.asarray(window)
            widths = bounds[:, 1] - bounds[:, 0]
            centers = bounds.mean(axis=1)
            typical_width = float(np.median(widths))
            if (np.quantile(widths, .9) - np.quantile(widths, .1) > typical_width * .40
                    or np.ptp(centers) > unit * .10):
                continue
            end = start + 19
            accepted = list(range(start, end + 1))
            missing = 0
            for y in range(end + 1, max_row):
                row = rows.get(y)
                if row is None:
                    missing += 1
                    if missing > 5:
                        break
                    continue
                left, right = row
                if (right - left > typical_width * 1.28
                        or right - left < typical_width * .65
                        or abs((left + right) / 2 - float(np.median(centers))) > unit * .18):
                    break
                missing = 0
                end = y
                accepted.append(y)
            # A V collar narrows exposed skin farther down, without making the
            # physical neck narrower. Measure its upper cross-sections, while
            # the longer trace above establishes support and a visible base.
            samples = np.array([rows[y] for y in range(start, start + 6) if y in rows])
            if len(samples) < 4:
                continue
            left, right = np.median(samples, axis=0)
            # Do not call a neck measured when one edge is cut off by the photo.
            edge_y = (start + end) / 2
            edge_points = [chin + lateral * ((x - origin_x) / scale)
                           + down * ((edge_y - origin_y) / scale) for x in (left, right)]
            if any(not (2 < p[0] < confidence.shape[1] - 3
                        and 2 < p[1] < confidence.shape[0] - 3) for p in edge_points):
                continue
            # Prefer upper, face-centered support; a second similar candidate
            # is treated as ambiguity rather than selecting a background patch.
            score = (min((end - start + 1) / unit, .35) * .2
                     - (start - origin_y) / unit * 3
                     - abs((left + right) / 2 - origin_x) / unit)
            candidate = (score, label, float(left), float(right), start, end)
            candidates.append(candidate)
            break
    candidates.sort(reverse=True)
    if not candidates:
        return fallback
    if len(candidates) > 1 and candidates[1][0] >= candidates[0][0] - .08:
        return fallback
    _, label, left, right, start, end = candidates[0]
    placement = _placement(chin, down, lateral, width,
                           (left - origin_x) / unit, (right - origin_x) / unit,
                           (start - origin_y) / unit, (end - origin_y) / unit, True)
    placement = _center_at_pose_level(placement, pose)
    upper = _upper_neck_band(body_binary, labels, label, origin_x, origin_y, unit)
    if upper is not None:
        left, right, level = upper
        top = chin + lateral * ((left + right) / 2 - origin_x) / scale + down * (level - origin_y) / scale
        edges = [chin + lateral * (x - origin_x) / scale + down * (level - origin_y) / scale
                 for x in (left, right)]
        if all(2 < p[0] < confidence.shape[1] - 3
               and 2 < p[1] < confidence.shape[0] - 3 for p in edges):
            placement = replace(placement, top=tuple(map(float, top)),
                                width=float((right - left) / scale), upper_measured=True)
    return placement
