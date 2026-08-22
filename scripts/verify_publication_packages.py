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
import time


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

# Inputs the guard scripts read, with where each comes from. Checked before --run-guards so a missing
# download fails in one clear line naming the file and its source, instead of a pandas stack trace six
# guards deep. Guards use paths relative to the repository root, so they are always run with cwd=ROOT.
GUARD_INPUTS: dict[str, str] = {
    "data/processed/analysis_dataset_dwell.csv":
        "built locally: run src/index/build_macro_panel.py, THEN src/index/build_dwell_index.py (in that order)",
    "data/processed/ais_dwell_census/monthly_dwell.csv":
        "five-port dwell census: Zenodo 10.5281/zenodo.21820262 version 2.0.0",
    "data/processed/ais_dwell_census_mode/monthly_mode_time.csv":
        "five-port mode census: Zenodo 10.5281/zenodo.21820262 version 2.0.0",
}
# Guards that stream the raw ping corpus rather than a monthly summary, so they take minutes rather than
# seconds. Named here so a long silence reads as expected rather than as a hang. run_guard prints the
# measured elapsed time for each, which is the number to trust -- these labels are only a warning that
# the guard is I/O bound.
SLOW_GUARDS: dict[str, str] = {
    "src/process_ais/ais_qc.py": "minutes: streams 107M LA/LB pings",
    "src/process_ais/port_call_segmentation.py": "minutes: re-segments the raw pings",
    "src/process_ais/mode_validation.py": "minutes: re-runs mode classification",
}

# Cross-document references are hard-coded numbers ("SI~S7", "Supplementary Table~S11") because the
# manuscript and its SI compile as separate documents, so LaTeX cannot link them and a \ref would break.
# Consequence: inserting a section or table in the SI silently renumbers every later target and turns a
# correct citation into a confidently wrong one. This table is the missing link. It records, for each
# literal number the main text uses, which SI item that number must name; reordering the SI then fails
# here instead of misdirecting a reader. Every literal in the main text must appear, so adding one is
# a deliberate act.
SI_CROSSREFS: dict[str, dict] = {
    "A": {
        "si": "paper_A_CEE_SI.tex",
        # "SI~SN"  ->  a distinctive phrase that must occur in the title of SI section N
        "sections": {
            1: "CARB calibration",
            4: "regime-definition grid",
            6: "difference-in-differences",
            7: "Era-boundary validation",
            8: "standing guard scripts",
            9: "Port-call segmentation",
            10: "robustness battery",
            11: "Social-cost derivation",
        },
        # "Supplementary Table~SN"  ->  the SI label that must carry number N
        "tables": {11: "tab:ed_summary"},
        # "Supplementary Fig.~SN"   ->  the SI label that must carry number N
        "figures": {1: "fig:reform"},
    },
}
DECLARATIONS = (
    "Independent Researcher, Tashkent, Uzbekistan",
    "Jack00040008@outlook.com",
    "0009-0003-5482-5526",
    "Acknowledgements",
    "Funding",
    "This research received no external funding.",
    "Competing interests",
)


# Evidence is hashed by CONTENT, not by line endings. See sha256() for why.
TEXT_EVIDENCE = {".csv", ".json", ".md", ".txt", ".tex", ".bib", ".geojson"}


def sha256(path: Path) -> str:
    """Hash evidence content with newlines normalised, so one digest is right on every platform.

    These digests were raw file hashes until 2026-08-22, which made them platform-dependent: git checks
    text out with CRLF on Windows and LF everywhere else, so on Linux 28 of the 41 claims reported
    "evidence hash changed" while not one byte of content differed. That reads like data corruption and
    stops a reproducer dead on the first command. Text evidence is therefore hashed with CRLF collapsed
    to LF; anything else is hashed as-is. Streaming keeps a one-byte carry so a CRLF straddling two
    blocks still normalises.
    """
    digest = hashlib.sha256()
    normalise = path.suffix.lower() in TEXT_EVIDENCE
    carry = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if not normalise:
                digest.update(block)
                continue
            block = carry + block
            carry = b"\r" if block.endswith(b"\r") else b""
            if carry:
                block = block[:-1]
            digest.update(block.replace(b"\r\n", b"\n"))
    if carry:
        digest.update(carry)
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

    si_crossref_check(paper, spec, text)

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


def si_crossref_check(paper: str, spec: dict, text: str) -> None:
    """Resolve the main text's hard-coded SI references against the SI's actual numbering.

    LaTeX numbers sections, tables and figures by order of appearance, so the SI source is the authority.
    We rebuild that order and check both directions: every registered number still names the item it is
    supposed to name, and every literal used in the main text is registered.
    """
    spec_refs = SI_CROSSREFS.get(paper)
    if not spec_refs:
        return
    si_path = bundle(spec) / spec_refs["si"]
    si = si_path.read_text(encoding="utf-8")

    titles = re.findall(r"^\\section\{(.+?)\}", si, flags=re.MULTILINE)
    tables = re.findall(r"\\label\{(tab:[^}]+)\}", si)
    figures = re.findall(r"\\label\{(fig:[^}]+)\}", si)

    for number, phrase in spec_refs["sections"].items():
        if number > len(titles):
            raise AssertionError(f"{spec['tex']}: cites SI~S{number} but {si_path.name} has "
                                 f"{len(titles)} sections")
        if phrase.lower() not in titles[number - 1].lower():
            raise AssertionError(
                f"{spec['tex']}: SI~S{number} should name a section about {phrase!r}, but section S{number} "
                f"of {si_path.name} is {titles[number - 1]!r} -- the SI was reordered; re-check every "
                "hard-coded SI reference in the main text and update SI_CROSSREFS")
    for kind, found, wanted, word in (
        ("Supplementary Table", tables, spec_refs["tables"], "table"),
        ("Supplementary Fig.", figures, spec_refs["figures"], "figure"),
    ):
        for number, label in wanted.items():
            if number > len(found):
                raise AssertionError(f"{spec['tex']}: cites {kind}~S{number} but {si_path.name} has "
                                     f"{len(found)} {word}s")
            if found[number - 1] != label:
                raise AssertionError(
                    f"{spec['tex']}: {kind}~S{number} should be {label}, but it is {found[number - 1]} "
                    f"in {si_path.name} -- the SI was reordered; update the main text and SI_CROSSREFS")

    # The other direction: an unregistered literal is a reference that nothing is checking.
    for pattern, registered, kind in (
        (r"SI~S(\d+)", spec_refs["sections"], "SI~S"),
        (r"Supplementary Table~S(\d+)", spec_refs["tables"], "Supplementary Table~S"),
        (r"Supplementary Fig\.~S(\d+)", spec_refs["figures"], "Supplementary Fig.~S"),
    ):
        unregistered = sorted({int(n) for n in re.findall(pattern, text)} - set(registered))
        if unregistered:
            raise AssertionError(
                f"{spec['tex']}: {kind}{unregistered} used in the main text but absent from "
                "SI_CROSSREFS -- register it so the reference is checked, or remove it")


def check_guard_inputs() -> None:
    """Fail once, clearly, if a guard input is absent -- not six guards deep in a stack trace."""
    missing = [(rel, src) for rel, src in GUARD_INPUTS.items() if not (ROOT / rel).is_file()]
    if missing:
        lines = [f"  {rel}\n      {src}" for rel, src in missing]
        raise FileNotFoundError(
            "cannot run the guards; these inputs are absent:\n" + "\n".join(lines)
            + "\n  (the two build_* stages must run in the order given, and the Zenodo files extract "
              "into data/processed/)")


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


def run_guard(rel: str, index: int = 0, total: int = 0) -> float:
    """Guard scripts assert their own headline numbers and exit non-zero on regression.

    Progress is printed before each guard rather than after, because three of them stream the raw ping
    corpus for minutes; without a line first, a correct run is indistinguishable from a hang.
    """
    note = SLOW_GUARDS.get(rel, "")
    counter = f"[{index}/{total}] " if total else ""
    print(f"  {counter}{rel}{f'  ({note})' if note else ''}", flush=True)
    start = time.monotonic()
    proc = subprocess.run([sys.executable, rel], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise AssertionError(f"guard failed after {elapsed:.0f}s: {rel}\n" + "\n".join(tail))
    print(f"      pass ({elapsed:.0f}s)", flush=True)
    return elapsed


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
        check_guard_inputs()
        print(f"running {len(guards)} guard scripts (each asserts its own headline numbers):", flush=True)
        spent = sum(run_guard(guard, i, len(guards)) for i, guard in enumerate(guards, 1))
        print(f"all {len(guards)} guards passed in {spent:.0f}s", flush=True)
    if run_tests and tests:
        subprocess.run([sys.executable, "-m", "pytest", "-q", *sorted(tests)], cwd=ROOT, check=True)
    print(f"verified {claims} claims across {len(papers)} paper(s): {', '.join(papers)}; "
          f"tests={len(tests) if run_tests else 0}; guards={len(guards) if run_guards else 0}; deep={deep}")


def main() -> None:
    # Guard output is ASCII, but a Windows console can still be on a code page that cannot encode a
    # replacement character echoed back from a failing guard. Ask for UTF-8 and carry on if unavailable.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
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
