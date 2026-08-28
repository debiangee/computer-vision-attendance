"""Replaceable local vision providers; no runtime model downloads."""

from .mock import MockVisionProvider
from .opencv import OpenCVVisionProvider
from .protocol import VisionObservationProvider, VisionSample, VisionStatus

__all__ = [
    "MockVisionProvider",
    "OpenCVVisionProvider",
    "VisionObservationProvider",
    "VisionSample",
    "VisionStatus",
]
