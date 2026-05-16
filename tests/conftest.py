"""Shared pytest fixtures for the PhotoConsole test suite."""
import pytest

# Minimal valid JPEG bytes (a 1×1 pixel JFIF file, no EXIF).
# This is a pre-baked constant so tests don't require Pillow at fixture time.
_MINIMAL_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10,  # SOI + APP0 marker + length
    0x4A, 0x46, 0x49, 0x46, 0x00,        # "JFIF\0" identifier
    0x01, 0x01,                            # version 1.1
    0x00,                                  # aspect ratio units (0 = no units)
    0x00, 0x01, 0x00, 0x01,               # X/Y density = 1×1
    0x00, 0x00,                            # no thumbnail
    # Minimal SOF0 (Start of Frame) for 1×1 greyscale
    0xFF, 0xC0, 0x00, 0x0B,               # SOF0 marker + length 11
    0x08,                                  # 8 bits precision
    0x00, 0x01, 0x00, 0x01,               # height=1, width=1
    0x01,                                  # 1 component
    0x01, 0x11, 0x00,                      # component ID, sampling, quantization table
    # Minimal DHT
    0xFF, 0xC4, 0x00, 0x1F,
    0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01,
    0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
    0x07, 0x08, 0x09, 0x0A, 0x0B,
    # Minimal SOS (Start of Scan) — single-byte scan data
    0xFF, 0xDA, 0x00, 0x08,
    0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xF8,
    # EOI
    0xFF, 0xD9,
])


@pytest.fixture
def sample_jpg(tmp_path) -> "pathlib.Path":
    """Return a path to a temporary minimal JPEG file for use in unit tests."""
    import pathlib
    path: pathlib.Path = tmp_path / "sample.jpg"
    path.write_bytes(_MINIMAL_JPEG)
    return path


@pytest.fixture
def tmp_catalog_path(tmp_path) -> "pathlib.Path":
    """Return a tmp_path-derived path for a SQLite catalog file.

    The file is NOT created or initialized here; Plan 02 provides the
    engine factory (in_memory_engine) that handles schema creation.
    """
    import pathlib
    return tmp_path / "test_catalog.db"


@pytest.fixture
def in_memory_engine():
    """Yield a SQLAlchemy in-memory SQLite engine with the schema applied.

    This fixture is provided here as a stub so Plan 02 can override it
    with the real ORM models once the catalog module is implemented.
    Plans that need a live engine must import from their own conftest
    or wait for Plan 02 to populate this fixture.
    """
    # Stub — Plan 02 will replace the body of this fixture with the real
    # ORM engine factory. Returning None here prevents AttributeError if
    # a test accidentally imports this fixture before Plan 02 is applied.
    return None
