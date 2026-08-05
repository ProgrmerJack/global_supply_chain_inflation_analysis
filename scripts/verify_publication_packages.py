"""Verify manuscript evidence hashes and optionally run focused tests, guard scripts and census checks.

Papers are addressed by the letters used everywhere else in the repository:

    A  paper_A_CEE.tex                    Communications Earth & Environment
    B  paper_B_scidata.tex                Scientific Data
    C  paper_C_measurement_validity.tex   Transportation Research Interdisciplinary Perspectives
    D  paper_D_spb_policy.tex             Ocean & Coastal Management

Each paper carries a claims ledger binding every headline to an evidence artifact (hashed), the
generator that produced it, and the tests or guard scripts that re-derive it.

    python scripts/verify_publication_packages.py --paper all
    python scripts/verify_publication_packages.py --paper all --run-tests
    python scripts/verify_publication_packages.py --paper A   --run-guards
    python scripts/verify_publication_packages.py --paper B   --deep
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

# abstract_limit is the target journal's own word cap; the build fails above it.
PAPERS: dict[str, dict] = {
    "A": {"bundle": "paper_A_CEE", "tex": "paper_A_CEE.tex", "abstract_limit": 150},
    "B": {"bundle": "paper_B_scidata", "tex": "paper_B_scidata.tex",
          "abstract_limit": 170, "scidata_headings": True, "title_limit": 110},
    "C": {"bundle": "paper_C_trip", "tex": "paper_C_measurement_validity.tex",
          "abstract_limit": 250, "highlights": True},
    "D": {"bundle": "paper_D_ocm", "tex": "paper_D_spb_policy.tex",
          "abstract_limit": 250, "highlights": True},
}
REQUIRED = {"claim_id", "status", "claim", "evidence_path", "evidence_sha256", "generator_path", "test_paths", "check"}
DECLARATIONS = (
    "Independent Researcher, Tashkent, Uzbekistan",
    "Jack00040008@outlook.com",
    "0009-0003-5482-5526",
    "Acknowledgements",
    "Funding",
    "This research received no external funding.",
    "Competing interests",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_claims(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    missing = REQUIRED - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    return rows


def bundle(spec: dict) -> Path:
    """Each paper is a self-sufficient directory under manuscript/."""
    return ROOT / "manuscript" / spec["bundle"]


def static_manuscript_check(paper: str, spec: dict) -> None:
    home = bundle(spec)
    path = home / spec["tex"]
    text = path.read_text(encoding="utf-8")
    for required in DECLARATIONS:
        if required.lower() not in text.lower():
            raise AssertionError(f"{path.name}: missing declaration or author field: {required}")

    # The bundle carries its own bib so it compiles standalone; it must match the master exactly.
    master_bib = (ROOT / "manuscript/references.bib").read_bytes()
    bundle_bib = home / "references.bib"
    if not bundle_bib.is_file() or bundle_bib.read_bytes() != master_bib:
        raise AssertionError(f"{spec['bundle']}/references.bib differs from manuscript/references.bib "
                             "— re-copy the master so the bundle stays self-sufficient")
    bib = bundle_bib.read_text(encoding="utf-8")
    available_keys = set(re.findall(r"^@\w+\{([^,]+),", bib, flags=re.MULTILINE))
    cited_keys = {
        key.strip()
        for group in re.findall(r"\\cite\w*\{([^}]+)\}", text)
        for key in group.split(",")
    }
    missing_keys = cited_keys - available_keys
    if missing_keys:
        raise AssertionError(f"{path.name}: missing bibliography keys {sorted(missing_keys)}")

    # Every display item must ship as a 300-dpi raster and a vector PDF inside the bundle.
    for stem in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", text):
        figure = home / "figures" / stem
        raster = figure if figure.suffix else figure.with_suffix(".png")
        vector = figure.with_suffix(".pdf")
        if not raster.is_file() or not vector.is_file():
            raise FileNotFoundError(f"{path.name}: missing PNG/PDF figure pair for {stem}")

    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, flags=re.DOTALL)
    if not abstract:
        raise AssertionError(f"{path.name}: missing abstract")
    abstract_words = re.findall(r"\b[\w'-]+\b", re.sub(r"\\\w+|[{}$]", " ", abstract.group(1)))
    if len(abstract_words) > spec["abstract_limit"]:
        raise AssertionError(f"{path.name}: abstract has {len(abstract_words)} words "
                             f"(limit {spec['abstract_limit']})")

    if spec.get("scidata_headings"):
        for heading in ("Background and Summary", "Methods", "Data Records", "Technical Validation",
                        "Usage Notes", "Data Availability", "Code Availability", "Author Contributions"):
            if f"\\section*{{{heading}}}" not in text:
                raise AssertionError(f"{path.name}: missing Scientific Data heading: {heading}")
        title = re.search(r"\\title\{([^}]+)\}", text)
        if not title or len(title.group(1)) > spec["title_limit"]:
            raise AssertionError(f"{path.name}: Scientific Data title exceeds {spec['title_limit']} characters")
        # AI-use disclosure is submitted through the journal's portal, not carried in the manuscript.

    if "highlights" in spec:
        keywords = re.search(r"\\textbf\{Keywords:\}\s*([^\n]+)", text)
        if not keywords or not 1 <= len(keywords.group(1).split(";")) <= 7:
            raise AssertionError(f"{path.name}: missing keywords")
        # The generative-AI declaration is entered in the Elsevier submission system, not the manuscript.
        for required in ("Article type:", "CRediT author statement"):
            if required not in text:
                raise AssertionError(f"{path.name}: missing Elsevier field: {required}")
        highlights = home / "highlights.txt"
        lines = [line.strip() for line in highlights.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not 3 <= len(lines) <= 5 or any(len(line) > 85 for line in lines):
            raise AssertionError(f"{spec['bundle']}/highlights.txt: require 3--5 lines of at most 85 characters")


def deep_check(name: str) -> None:
    if not name:
        return
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=4")
    if name == "national_census":
        actual = con.execute(
            """SELECT count(*), count(DISTINCT mmsi), count(DISTINCT port_complex_id),
                      count(DISTINCT CAST(timestamp AT TIME ZONE 'UTC' AS DATE))
               FROM read_parquet(?, union_by_name=true, hive_partitioning=false)""",
            [str(ROOT / "data/interim/national_pings/year=*/month=*/*.parquet")],
        ).fetchone()
        expected = (463_113_836, 23_392, 15, 4_018)
    elif name == "historical_census":
        recent = con.execute(
            "SELECT count(*) FROM read_parquet(?, union_by_name=true, hive_partitioning=false)",
            [str(ROOT / "data/processed/ais_dwell_census_mode/port_pings/**/*.parquet")],
        ).fetchone()[0]
        early = con.execute(
            "SELECT count(*) FROM read_parquet(?, union_by_name=true, hive_partitioning=false)",
            [str(ROOT / "data/processed/ais_dwell_census_mode_2009_2014_v2/port_pings_fgdb/**/*.parquet")],
        ).fetchone()[0]
        actual, expected = (recent, early, recent + early), (134_527_203, 74_981_167, 209_508_370)
    else:
        raise ValueError(f"unknown deep check: {name}")
    con.close()
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected}, got {actual}")


def run_guard(rel: str) -> None:
    """Guard scripts assert their own headline numbers and exit non-zero on regression."""
    proc = subprocess.run([sys.executable, rel], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise AssertionError(f"guard failed: {rel}\n" + "\n".join(tail))


def verify(papers: list[str], run_tests: bool, deep: bool, run_guards: bool) -> None:
    tests: set[str] = set()
    checks: set[str] = set()
    guards: list[str] = []
    claims = 0
    for paper in papers:
        spec = PAPERS[paper]
        static_manuscript_check(paper, spec)
        for row in read_claims(bundle(spec) / "claims.csv"):
            claims += 1
            evidence = ROOT / row["evidence_path"]
            generator = ROOT / row["generator_path"]
            if not evidence.is_file() or not generator.is_file():
                raise FileNotFoundError(f"{row['claim_id']}: missing evidence or generator")
            actual = sha256(evidence)
            if actual != row["evidence_sha256"]:
                raise AssertionError(f"{row['claim_id']}: evidence hash changed ({actual})")
            tests.update(x for x in row["test_paths"].split(";") if x)
            if row["check"]:
                checks.add(row["check"])
            for guard in row.get("guard", "").split(";"):
                if guard and guard not in guards:
                    guards.append(guard)
    if deep:
        for check in sorted(checks):
            deep_check(check)
    if run_guards:
        for guard in guards:
            run_guard(guard)
    if run_tests and tests:
        subprocess.run([sys.executable, "-m", "pytest", "-q", *sorted(tests)], cwd=ROOT, check=True)
    print(f"verified {claims} claims across {len(papers)} paper(s): {', '.join(papers)}; "
          f"tests={len(tests) if run_tests else 0}; guards={len(guards) if run_guards else 0}; deep={deep}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper", choices=[*PAPERS, "all"], default="all")
    parser.add_argument("--run-tests", action="store_true", help="run the focused pytest set")
    parser.add_argument("--run-guards", action="store_true",
                        help="re-run the assert-guarded analysis scripts named in the ledgers")
    parser.add_argument("--deep", action="store_true", help="stream large parquet corpora and verify census counts")
    args = parser.parse_args()
    verify(list(PAPERS) if args.paper == "all" else [args.paper],
           args.run_tests, args.deep, args.run_guards)


if __name__ == "__main__":
    main()
