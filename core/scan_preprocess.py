"""OpenCV preprocessing for scanned drawings: deskew → denoise → binarize.

Basic working implementation for v1. Input is a BGR/gray image as returned by
``cv2.imread``; output is a single-channel image suitable for
:func:`core.vectorize.vectorize` (white background, dark strokes).
"""

from __future__ import annotations

import cv2
import numpy as np


def preprocess_scan(image: np.ndarray) -> np.ndarray:
    """Clean a scanned drawing and return a binarized single-channel image.

    Steps: grayscale → median denoise → estimate skew angle from the largest
    dark-ink moment orientation → rotate to deskew → Otsu binarize with
    inverted polarity flipped back to white-background/black-strokes.
    """
    if image is None or image.size == 0:
        raise ValueError("preprocess_scan() got an empty image")

    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # gentle denoise — preserves thin dimension lines better than heavy blur
    gray = cv2.medianBlur(gray, 3)

    # --- deskew -----------------------------------------------------------
    # orientation of the dominant ink mass via image moments
    dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(dark > 0))
    angle = 0.0
    if len(coords) > 500:
        (cx, cy), (w, h), raw_angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))
        # minAreaRect angles are ambiguous by 90°; normalize into [-45, 45]
        if raw_angle < -45:
            raw_angle += 90
        angle = float(raw_angle)
        if abs(angle) < 0.3 or abs(angle) > 45:
            angle = 0.0  # keep only plausible scan skew

    if angle != 0.0:
        h0, w0 = gray.shape
        matrix = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), angle, 1.0)
        gray = cv2.warpAffine(gray, matrix, (w0, h0),
                              flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=255)

    # --- binarize ----------------------------------------------------------
    cleaned = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=31, C=15,
    )
    # adaptive threshold gives black=text/lines on white — enforce explicitly
    if float(np.mean(cleaned)) < 127:
        cleaned = cv2.bitwise_not(cleaned)
    return cleaned
