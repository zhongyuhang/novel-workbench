"""ADR-001 canonical body format."""

import tomllib
from pathlib import Path

import app
from app.core.content import CANONICAL_CONTENT_FORMAT, CANONICAL_CONTENT_FORMAT_VERSION

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_format_is_tiptap_json_v1() -> None:
    assert CANONICAL_CONTENT_FORMAT == "tiptap_json"
    assert CANONICAL_CONTENT_FORMAT_VERSION == 1


def test_package_version_matches_pyproject() -> None:
    with (BACKEND_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    assert project["project"]["version"] == app.__version__
