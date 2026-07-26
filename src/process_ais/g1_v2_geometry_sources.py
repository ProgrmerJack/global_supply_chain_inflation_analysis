"""Immutable, resumable cache for outcome-free G1-v2 geometry documentation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Mapping

import pandas as pd

try:
    from .source_manifest import (
        FILE_MANIFEST_COLUMNS,
        build_file_manifest_record_from_counts,
        cache_immutable_source_document,
        normalise_file_manifest,
    )
except ImportError:  # pragma: no cover - direct script execution
    from source_manifest import (
        FILE_MANIFEST_COLUMNS,
        build_file_manifest_record_from_counts,
        cache_immutable_source_document,
        normalise_file_manifest,
    )


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config/registries/g1_v2_geometry_source_registry_draft.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data/external/g1_v2_geometry_sources"
REQUIRED_SOURCE_COLUMNS = (
    "document_id",
    "gateway_id",
    "source_file",
    "source_url",
    "cache_action",
)
_CACHE_NOW = "cache_now"
_EXTERNAL_ACCESS_REQUIRED = "external_access_required"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_source_registry(path: Path | str) -> pd.DataFrame:
    registry = pd.read_csv(path, dtype=str, keep_default_na=False)
    if missing := set(REQUIRED_SOURCE_COLUMNS) - set(registry.columns):
        raise ValueError(f"geometry source registry missing columns: {sorted(missing)}")
    registry = registry.loc[:, REQUIRED_SOURCE_COLUMNS].copy()
    if registry.empty:
        raise ValueError("geometry source registry has no records")
    if registry.document_id.duplicated().any():
        raise ValueError("geometry source registry contains duplicate document_id values")
    if registry.source_file.duplicated().any():
        raise ValueError("geometry source registry contains duplicate source_file values")
    if not registry.source_url.str.startswith("https://").all():
        raise ValueError("geometry source registry requires HTTPS source URLs")
    if not registry.source_file.map(lambda value: Path(value).name == value and value not in {"", ".", ".."}).all():
        raise ValueError("geometry source files must be simple filenames")
    invalid_actions = sorted(set(registry.cache_action) - {_CACHE_NOW, _EXTERNAL_ACCESS_REQUIRED})
    if invalid_actions:
        raise ValueError(f"geometry source registry has invalid cache actions: {invalid_actions}")
    if not registry.cache_action.eq(_CACHE_NOW).any():
        raise ValueError("geometry source registry has no cacheable public document")
    return registry.sort_values("document_id", kind="stable").reset_index(drop=True)


def _sidecar_path(document_path: Path) -> Path:
    return document_path.with_name(document_path.name + ".manifest.json")


def _load_verified_sidecar(document_path: Path, sidecar_path: Path, source_url: str, gateway_id: str) -> dict[str, object]:
    if document_path.exists() != sidecar_path.exists():
        raise FileExistsError(
            "geometry document and provenance sidecar must either both exist or both be absent: "
            f"{document_path}"
        )
    if not document_path.exists():
        return {}
    try:
        record = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"geometry document provenance sidecar is unreadable: {sidecar_path}") from error
    if not isinstance(record, dict) or set(FILE_MANIFEST_COLUMNS) - set(record):
        raise ValueError(f"geometry document provenance sidecar has an invalid schema: {sidecar_path}")
    if record["source_file"] != document_path.name or record["source_url"] != source_url:
        raise ValueError(f"geometry document provenance does not match the declared source: {document_path}")
    if record["port_complex_id"] != gateway_id or record["sha256"] != _sha256(document_path):
        raise ValueError(f"geometry document provenance does not match its local bytes: {document_path}")
    return record


def _cached_records(registry: pd.DataFrame, output_dir: Path) -> list[dict[str, object]]:
    return [
        record
        for row in registry.itertuples(index=False)
        if (
            record := _load_verified_sidecar(
                output_dir / row.source_file,
                _sidecar_path(output_dir / row.source_file),
                row.source_url,
                row.gateway_id,
            )
        )
    ]


def _write_append_only_manifest(records: list[dict[str, object]], manifest_path: Path) -> pd.DataFrame:
    manifest = normalise_file_manifest(records)
    rendered = manifest.to_csv(index=False, lineterminator="\n")
    if manifest_path.exists():
        existing = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
        expected = manifest.fillna("").astype(str)
        if list(existing.columns) != FILE_MANIFEST_COLUMNS or existing.duplicated(
            ["port_complex_id", "source_file"]
        ).any():
            raise ValueError("geometry source manifest has an invalid schema")
        existing_rows = {
            (row["port_complex_id"], row["source_file"]): tuple(row[column] for column in FILE_MANIFEST_COLUMNS)
            for _, row in existing.iterrows()
        }
        expected_rows = {
            (row["port_complex_id"], row["source_file"]): tuple(row[column] for column in FILE_MANIFEST_COLUMNS)
            for _, row in expected.iterrows()
        }
        if not set(existing_rows).issubset(expected_rows) or any(
            expected_rows[key] != row for key, row in existing_rows.items()
        ):
            raise ValueError("geometry source manifest would alter existing provenance")
        if manifest_path.read_text(encoding="utf-8") == rendered:
            return manifest
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(rendered, encoding="utf-8")
    return manifest


def cache_declared_geometry_sources(
    registry_path: Path | str = DEFAULT_REGISTRY,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    retrieved_at: str,
    get,
) -> pd.DataFrame:
    """Cache declared public geometry documents once, with per-file resume evidence."""
    registry = _load_source_registry(registry_path)
    output_dir = Path(output_dir)
    for row in registry.itertuples(index=False):
        if row.cache_action != _CACHE_NOW:
            continue
        document_path = output_dir / row.source_file
        sidecar_path = _sidecar_path(document_path)
        record = _load_verified_sidecar(document_path, sidecar_path, row.source_url, row.gateway_id)
        if not record:
            record = cache_immutable_source_document(
                document_path,
                source_url=row.source_url,
                retrieved_at=retrieved_at,
                parser_version="g1-v2-geometry-source-cache-v1",
                port_complex_id=row.gateway_id,
                get=get,
            )
            sidecar_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _write_append_only_manifest(_cached_records(registry, output_dir), output_dir / "source_manifest.csv")


def cache_authorized_geometry_documents(
    registry_path: Path | str = DEFAULT_REGISTRY,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    authorized_documents: Mapping[str, Path | str],
    retrieved_at: str,
) -> pd.DataFrame:
    """Cache authority-supplied files for declared access-blocked geometry sources once."""
    if not authorized_documents:
        raise ValueError("at least one authorized geometry document is required")

    registry = _load_source_registry(registry_path)
    rows = {row.document_id: row for row in registry.itertuples(index=False)}
    unknown = sorted(set(authorized_documents) - set(rows))
    if unknown:
        raise ValueError(f"authorized geometry documents are not declared: {unknown}")

    output_dir = Path(output_dir)
    for document_id, supplied_path in sorted(authorized_documents.items()):
        row = rows[document_id]
        if row.cache_action != _EXTERNAL_ACCESS_REQUIRED:
            raise ValueError(f"authorized geometry document is not access-blocked: {document_id}")
        supplied_path = Path(supplied_path)
        if not supplied_path.is_file():
            raise FileNotFoundError(f"authorized geometry document is missing: {supplied_path}")

        document_path = output_dir / row.source_file
        sidecar_path = _sidecar_path(document_path)
        existing = _load_verified_sidecar(document_path, sidecar_path, row.source_url, row.gateway_id)
        if existing:
            if existing["sha256"] != _sha256(supplied_path):
                raise ValueError(f"authorized geometry document conflicts with cached provenance: {document_id}")
            continue
        if supplied_path.resolve() == document_path.resolve():
            raise ValueError("authorized geometry document must be supplied outside the immutable cache")

        document_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(supplied_path, document_path)
        record = build_file_manifest_record_from_counts(
            document_path,
            source_url=row.source_url,
            retrieved_at=retrieved_at,
            raw_row_count=0,
            accepted_row_count=0,
            rejected_row_count=0,
            rejection_counts={},
            first_timestamp=None,
            last_timestamp=None,
            parser_version="g1-v2-geometry-source-cache-v1",
            port_complex_id=row.gateway_id,
        )
        record.update(
            delivery_method="authorized_external_file",
            delivered_file_name=supplied_path.name,
        )
        sidecar_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return _write_append_only_manifest(_cached_records(registry, output_dir), output_dir / "source_manifest.csv")


def main() -> int:
    cache_declared_geometry_sources(
        retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        get=__import__("requests").get,
    )
    print(f"cached declared G1-v2 geometry sources in {DEFAULT_OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    raise SystemExit(main())
