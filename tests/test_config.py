"""Tests for photoconsole.config — Source/Config dataclasses and load_config YAML loader."""
import os
import textwrap

import pytest
from photoconsole.config import Config, ConsolidationConfig, Source, load_config
from photoconsole.constants import MEDIA_EXTENSIONS


# ---------------------------------------------------------------------------
# Helper: write a minimal valid YAML config to a tmp file
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, content: str, filename: str = "test_config.yaml"):
    path = tmp_path / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 1. config.example.yaml loads without error
# ---------------------------------------------------------------------------

class TestExampleConfig:
    def test_example_config_loads_ok(self):
        """config.example.yaml must parse without raising."""
        c = load_config("config.example.yaml")
        assert isinstance(c, Config)

    def test_example_config_has_at_least_one_source(self):
        c = load_config("config.example.yaml")
        assert len(c.sources) >= 1

    def test_example_config_catalog_path_is_absolute(self):
        c = load_config("config.example.yaml")
        assert os.path.isabs(c.catalog_path), f"catalog_path not absolute: {c.catalog_path}"

    def test_example_config_catalog_path_no_tilde(self):
        c = load_config("config.example.yaml")
        assert "~" not in c.catalog_path, "catalog_path should be ~-expanded"

    def test_example_config_catalog_path_ends_with_db(self):
        c = load_config("config.example.yaml")
        assert c.catalog_path.endswith(".db")

    def test_example_config_extensions_lower_with_dot(self):
        c = load_config("config.example.yaml")
        for ext in c.include_extensions:
            assert ext.startswith("."), f"{ext!r} should start with '.'"
            assert ext == ext.lower(), f"{ext!r} should be lower-case"

    def test_example_config_hashing_max_workers_is_positive_int(self):
        c = load_config("config.example.yaml")
        assert isinstance(c.hashing_max_workers, int)
        assert c.hashing_max_workers >= 1

    def test_example_config_sources_have_valid_type(self):
        c = load_config("config.example.yaml")
        for src in c.sources:
            assert src.type in {"local", "rclone"}, f"Unexpected source type: {src.type!r}"


# ---------------------------------------------------------------------------
# 2. Validation: missing required keys
# ---------------------------------------------------------------------------

class TestMissingRequiredKeys:
    def test_missing_catalog_path_raises_valueerror_with_substring(self, tmp_path):
        yaml_text = """
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="catalog_path"):
            load_config(path)

    def test_missing_sources_raises_valueerror_with_substring(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="sources"):
            load_config(path)

    def test_empty_sources_list_raises_valueerror_with_substring(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources: []
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="sources"):
            load_config(path)


# ---------------------------------------------------------------------------
# 3. Validation: unknown source type
# ---------------------------------------------------------------------------

class TestUnknownSourceType:
    def test_unknown_source_type_raises_valueerror(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Mystery"
                type: sftp
                path: /remote/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="unknown source type"):
            load_config(path)


# ---------------------------------------------------------------------------
# 4. Validation: missing path/remote per source type
# ---------------------------------------------------------------------------

class TestSourceTypeFieldValidation:
    def test_local_without_path_raises_valueerror(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local No Path"
                type: local
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="local source requires path"):
            load_config(path)

    def test_rclone_without_remote_raises_valueerror(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Rclone No Remote"
                type: rclone
        """
        path = write_yaml(tmp_path, yaml_text)
        with pytest.raises(ValueError, match="rclone source requires remote"):
            load_config(path)


# ---------------------------------------------------------------------------
# 5. Default: hashing_max_workers falls back to os.cpu_count() or 1
# ---------------------------------------------------------------------------

class TestHashingMaxWorkersDefault:
    def test_max_workers_default_equals_cpu_count_or_1(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        expected = os.cpu_count() or 1
        assert c.hashing_max_workers == expected

    def test_max_workers_from_config_overrides_default(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            hashing:
              max_workers: 2
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert c.hashing_max_workers == 2


# ---------------------------------------------------------------------------
# 6. Extension normalization
# ---------------------------------------------------------------------------

class TestExtensionNormalization:
    def test_uppercase_extension_normalized_to_lowercase(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            include_extensions:
              - .JPG
              - JPEG
              - .PNG
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert ".jpg" in c.include_extensions
        assert ".jpeg" in c.include_extensions
        assert ".png" in c.include_extensions

    def test_extension_without_leading_dot_gets_dot_prepended(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            include_extensions:
              - jpg
              - mp4
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert ".jpg" in c.include_extensions
        assert ".mp4" in c.include_extensions

    def test_extensions_default_to_media_extensions_when_omitted(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert c.include_extensions == MEDIA_EXTENSIONS

    def test_include_extensions_is_frozenset(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert isinstance(c.include_extensions, frozenset)


# ---------------------------------------------------------------------------
# 7. Source dataclass fields
# ---------------------------------------------------------------------------

class TestSourceDataclass:
    def test_source_name_preserved(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "NAS Photos"
                type: local
                path: /mnt/nas/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert c.sources[0].name == "NAS Photos"

    def test_local_source_path_preserved(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /mnt/photos
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert c.sources[0].path == "/mnt/photos"

    def test_rclone_source_remote_preserved(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Google Drive"
                type: rclone
                remote: "gdrive:"
        """
        path = write_yaml(tmp_path, yaml_text)
        c = load_config(path)
        assert c.sources[0].remote == "gdrive:"


# ---------------------------------------------------------------------------
# 8. Threat model: yaml.safe_load is used (no arbitrary object construction)
# ---------------------------------------------------------------------------

class TestYamlSafety:
    def test_yaml_safe_load_rejects_python_objects(self, tmp_path):
        """Verify that load_config uses yaml.safe_load (T-01-01).
        A YAML document with !!python/object tags must NOT construct arbitrary objects.
        """
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: !!python/object:os.system [echo injected]
                type: local
                path: /tmp
        """
        path = write_yaml(tmp_path, yaml_text)
        # yaml.safe_load raises yaml.constructor.ConstructorError for !!python/ tags
        import yaml
        with pytest.raises((yaml.YAMLError, ValueError, Exception)):
            load_config(path)


# ---------------------------------------------------------------------------
# 9. ConsolidationConfig dataclass (Task 1 — RED phase)
# ---------------------------------------------------------------------------

class TestConsolidationConfigDataclass:
    def test_consolidation_config_default_destination_path_is_empty_string(self):
        c = ConsolidationConfig()
        assert c.destination_path == ''

    def test_consolidation_config_default_source_priority_is_empty_list(self):
        c = ConsolidationConfig()
        assert c.source_priority == []

    def test_consolidation_config_with_destination_path(self):
        c = ConsolidationConfig(destination_path='D:\\PhotoLibrary')
        assert c.destination_path == 'D:\\PhotoLibrary'

    def test_consolidation_config_with_source_priority(self):
        c = ConsolidationConfig(source_priority=['D: SSD', 'OneDrive'])
        assert c.source_priority == ['D: SSD', 'OneDrive']

    def test_consolidation_config_full_construction(self):
        c = ConsolidationConfig(destination_path='D:\\test', source_priority=['A', 'B'])
        assert c.destination_path == 'D:\\test'
        assert c.source_priority == ['A', 'B']

    def test_config_has_consolidation_field_with_default(self):
        cfg = Config(sources=[], catalog_path='/tmp/x.db')
        assert hasattr(cfg, 'consolidation')
        assert isinstance(cfg.consolidation, ConsolidationConfig)

    def test_config_consolidation_default_destination_path_is_empty(self):
        cfg = Config(sources=[], catalog_path='/tmp/x.db')
        assert cfg.consolidation.destination_path == ''

    def test_config_consolidation_default_source_priority_is_empty_list(self):
        cfg = Config(sources=[], catalog_path='/tmp/x.db')
        assert cfg.consolidation.source_priority == []

    def test_config_consolidation_accepts_kwarg(self):
        consolidation = ConsolidationConfig(destination_path='D:\\lib', source_priority=['X'])
        cfg = Config(sources=[], catalog_path='/tmp/x.db', consolidation=consolidation)
        assert cfg.consolidation.destination_path == 'D:\\lib'
        assert cfg.consolidation.source_priority == ['X']

    def test_existing_config_construction_without_consolidation_kwarg_still_works(self):
        """Regression: existing code that does not pass consolidation= must still work."""
        cfg = Config(
            sources=[],
            catalog_path='/tmp/x.db',
            include_extensions=frozenset({'.jpg'}),
            exclude_patterns=['*.tmp'],
            hashing_max_workers=4,
        )
        assert cfg.consolidation.destination_path == ''


# ---------------------------------------------------------------------------
# 10. load_config() consolidation YAML parsing (Task 2 — RED phase)
# ---------------------------------------------------------------------------

class TestLoadConfigConsolidation:
    def _write_config(self, tmp_path, content: str):
        """Write a YAML config string to a temp file and return its path."""
        return write_yaml(tmp_path, content)

    def test_load_config_no_consolidation_section_gives_empty_defaults(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        assert cfg.consolidation.destination_path == ''
        assert cfg.consolidation.source_priority == []

    def test_load_config_consolidation_destination_path_normalized(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            consolidation:
              destination_path: ~/PhotoLibrary
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        # Must be absolute (no tilde)
        assert os.path.isabs(cfg.consolidation.destination_path)
        assert '~' not in cfg.consolidation.destination_path

    def test_load_config_consolidation_destination_path_empty_stays_empty(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            consolidation:
              source_priority:
                - X
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        assert cfg.consolidation.destination_path == ''

    def test_load_config_consolidation_source_priority_list(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            consolidation:
              source_priority:
                - "D: SSD"
                - OneDrive
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        assert cfg.consolidation.source_priority == ['D: SSD', 'OneDrive']

    def test_load_config_consolidation_source_priority_is_list_type(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            consolidation:
              source_priority:
                - A
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        assert isinstance(cfg.consolidation.source_priority, list)

    def test_load_config_consolidation_both_fields(self, tmp_path):
        yaml_text = """
            catalog_path: ~/.photoconsole/catalog.db
            sources:
              - name: "Local"
                type: local
                path: /tmp/photos
            consolidation:
              destination_path: /tmp/lib
              source_priority:
                - X
                - Y
        """
        path = self._write_config(tmp_path, yaml_text)
        cfg = load_config(path)
        assert os.path.isabs(cfg.consolidation.destination_path)
        assert cfg.consolidation.source_priority == ['X', 'Y']
