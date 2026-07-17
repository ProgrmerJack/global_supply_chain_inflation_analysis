"""Archive outcome-blind metadata for the Phase-7 product-port feasibility audit.

This module deliberately excludes Census trade values and BLS price observations.
It caches only schemas, classification dictionaries, concordance metadata and the
direct novelty benchmark needed to decide whether an admissible design can exist.

Run: python src/acquire/product_port_metadata.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _http import get_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/external/product_port_metadata"

CENSUS_PORTHS_VARIABLES = (
    "https://api.census.gov/data/timeseries/intltrade/imports/porths/variables.json"
)
def _sources() -> dict[str, dict[str, str]]:
    sources: dict[str, dict[str, str]] = {
        "census_porths_variables.json": {
            "owner": "U.S. Census Bureau",
            "url": CENSUS_PORTHS_VARIABLES,
            "role": "Port-HS API variable schema",
            "format": "json",
        },
        "census_porths_dataset.json": {
            "owner": "U.S. Census Bureau",
            "url": "https://api.census.gov/data/timeseries/intltrade/imports/porths.json",
            "role": "Port-HS API dataset and temporal metadata",
            "format": "json",
        },
        "census_porths_examples.json": {
            "owner": "U.S. Census Bureau",
            "url": (
                "https://api.census.gov/data/timeseries/intltrade/imports/"
                "porths/examples.json"
            ),
            "role": "Port-HS API metadata-only example schema",
            "format": "json",
        },
        "census_porths_geography.json": {
            "owner": "U.S. Census Bureau",
            "url": (
                "https://api.census.gov/data/timeseries/intltrade/imports/"
                "porths/geography.json"
            ),
            "role": "Port-HS API geographic predicate metadata",
            "format": "json",
        },
        "bls_cu_item.txt": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": "https://download.bls.gov/pub/time.series/CU/cu.item",
            "role": "Published CPI item dictionary",
            "format": "text",
        },
        "bls_cu_series.txt": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": "https://download.bls.gov/pub/time.series/CU/cu.series",
            "role": "CPI series metadata without observations",
            "format": "text",
        },
        "bls_cu_documentation.txt": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": "https://download.bls.gov/pub/time.series/CU/cu.txt",
            "role": "CPI flat-file schema documentation",
            "format": "text",
        },
        "bls_ce_cpi_concordance_2020.xlsx": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": (
                "https://www.bls.gov/cpi/additional-resources/"
                "ce-cpi-concordance-2020.xlsx"
            ),
            "role": "Historical CE-UCC to CPI-ELI concordance",
            "format": "xlsx",
        },
        "bls_ce_cpi_concordance_current.xlsx": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": (
                "https://www.bls.gov/cpi/additional-resources/"
                "ce-cpi-concordance.xlsx"
            ),
            "role": "Current CE-UCC to CPI-ELI concordance",
            "format": "xlsx",
        },
        "bls_cpi_item_aggregation_trees.xlsx": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": (
                "https://www.bls.gov/cpi/additional-resources/"
                "cpi-item-aggregation-trees.xlsx"
            ),
            "role": "CPI item hierarchy metadata",
            "format": "xlsx",
        },
        "bls_cpi_basic_item_aggregation.xlsx": {
            "owner": "U.S. Bureau of Labor Statistics",
            "url": (
                "https://www.bls.gov/cpi/additional-resources/"
                "cpi-basic-item-aggregation.xlsx"
            ),
            "role": "CPI basic-item aggregation metadata",
            "format": "xlsx",
        },
    }
    return sources


SOURCES = _sources()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate(content: bytes, kind: str, name: str) -> None:
    if len(content) < 20:
        raise RuntimeError(f"metadata response is implausibly short: {name}")
    if kind == "json":
        parsed = json.loads(content.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError(f"unexpected Census metadata schema: {name}")
        if name == "census_porths_variables.json" and "variables" not in parsed:
            raise RuntimeError(f"unexpected Census variable schema: {name}")
    elif kind == "pdf" and not content.startswith(b"%PDF"):
        raise RuntimeError(f"official response is not a PDF: {name}")
    elif kind == "xlsx" and not content.startswith(b"PK"):
        raise RuntimeError(f"official response is not an XLSX workbook: {name}")
    elif kind == "text":
        decoded = content[:5000].decode("utf-8", "ignore").lower()
        if "<!doctype html" in decoded or "<html" in decoded:
            raise RuntimeError(f"official text response is an HTML error page: {name}")


def _verified(path: Path, *, allow_unregistered: bool = False) -> dict[str, object] | None:
    sidecar = path.with_suffix(path.suffix + ".manifest.json")
    if not path.exists():
        return None
    if not sidecar.exists():
        if allow_unregistered:
            return None
        raise RuntimeError(f"missing provenance sidecar: {path.name}")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata["sha256"] != sha256(path.read_bytes()):
        raise RuntimeError(f"cached metadata hash mismatch: {path.name}")
    return metadata


def acquire(fetch=get_bytes, *, register_existing: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for name, source in SOURCES.items():
        path = OUT / name
        metadata = _verified(path, allow_unregistered=register_existing)
        if metadata is None:
            if path.exists() and register_existing:
                content = path.read_bytes()
                retrieval_path = "browser_download_after_direct_origin_rejected_automation"
            elif path.exists():
                raise RuntimeError(
                    f"unregistered metadata file exists: {path.name}; "
                    "use --register-existing only for files downloaded from the declared origin"
                )
            else:
                content = fetch(source["url"])
                retrieval_path = "direct_http"
            _validate(content, source["format"], name)
            if not path.exists():
                path.write_bytes(content)
            metadata = {
                "source_owner": source["owner"],
                "source_url": source["url"],
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "bytes": len(content),
                "sha256": sha256(content),
                "role": source["role"],
                "scope": "metadata_or_method_only; no trade values or price observations",
                "retrieval_path": retrieval_path,
            }
            path.with_suffix(path.suffix + ".manifest.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
        rows.append({"artifact": name, **metadata})

    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / "source_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)} outcome-blind product-port metadata artifacts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--register-existing",
        action="store_true",
        help="hash browser-downloaded files already placed at their declared output paths",
    )
    args = parser.parse_args()
    acquire(register_existing=args.register_existing)
