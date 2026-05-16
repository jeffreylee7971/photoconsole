"""Media extension allow-lists and shared constants."""

PHOTO_EXTENSIONS: frozenset[str] = frozenset({'.jpg', '.jpeg', '.png', '.gif'})

VIDEO_EXTENSIONS: frozenset[str] = frozenset({'.mp4', '.mov', '.avi'})

MEDIA_EXTENSIONS: frozenset[str] = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

CHUNK_SIZE: int = 8 * 1024  # 8192 bytes — streaming hash chunk size
