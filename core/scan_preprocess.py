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

    # --- deskew (projection profile: horizontal-line alignment concentrates ink
    # into few rows — sub-degree accurate for line drawings, sign-agnostic) -----
    def _rotate(src, a):
        h0, w0 = src.shape
        matrix = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), a, 1.0)
        return cv2.warpAffine(src, matrix, (w0, h0),
                              flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=255)

    def _projection_score(src):
        bw = cv2.threshold(src, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        proj = np.count_nonzero(bw, axis=1).astype(np.float64)
        return float(proj.var())

    coarse = np.arange(-5.0, 5.0 + 1e-9, 0.25)
    scores = [_projection_score(_rotate(gray, a)) for a in coarse]
    best = float(coarse[int(np.argmax(scores))])
    fine = np.arange(best - 0.24, best + 0.24 + 1e-9, 0.06)
    scores = [_projection_score(_rotate(gray, a)) for a in fine]
    best = float(fine[int(np.argmax(scores))])
    angle = best if abs(best) >= 0.06 else 0.0
    if angle != 0.0 and abs(angle) <= 15.0:
        gray = _rotate(gray, angle)

    # --- binarize ----------------------------------------------------------
    cleaned = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=31, C=15,
    )
    # adaptive threshold gives black=text/lines on white — enforce explicitly
    if float(np.mean(cleaned)) < 127:
        cleaned = cv2.bitwise_not(cleaned)
    return cleaned
