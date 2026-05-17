"""Media extension allow-lists and shared constants."""

PHOTO_EXTENSIONS: frozenset[str] = frozenset({
    # Common formats
    '.jpg', '.jpeg', '.png', '.gif',
    # Apple / modern
    '.heic', '.heif',
    # Raw formats
    '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng',
    # Other
    '.tiff', '.tif', '.bmp', '.webp',
})

VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    # Common formats
    '.mp4', '.mov', '.avi',
    # Broader coverage
    '.mkv', '.wmv', '.flv', '.m4v', '.3gp',
})

MEDIA_EXTENSIONS: frozenset[str] = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

CHUNK_SIZE: int = 8 * 1024  # 8192 bytes — streaming hash chunk size
