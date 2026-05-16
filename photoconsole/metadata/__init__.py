"""Metadata extraction package — photo EXIF and video ffprobe."""
from photoconsole.metadata.photo import extract_photo_metadata
from photoconsole.metadata.video import check_ffprobe_available, extract_video_metadata

__all__ = [
    "extract_photo_metadata",
    "extract_video_metadata",
    "check_ffprobe_available",
]
