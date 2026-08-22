from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import tempfile

import pytest


def _load_verifier(root: Path):
    spec = spec_from_file_location("publication_verifier", root / "scripts/verify_publication_packages.py")
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_publication_packages_static() -> None:
    root = Path(__file__).resolve().parents[1]
    module = _load_verifier(root)
    module.verify(["A", "B", "C", "D"], run_tests=False, deep=False, run_guards=False)
    # Papers are addressed by letter; figures follow the same letters. Until 2026-08-05 the figure
    # files were named paper1_/paper2_/paper3_ and mapped to B/C/D, which read as an off-by-one.
    expected = {
        "A": ("census", "emissions", "map", "irf", "reform_event_study"),
        "B": ("graphical_abstract", "scope_map", "coverage", "activity", "characteristics"),
        "C": ("graphical_abstract", "g1_correlations", "g1_scorecard", "spb_placebos", "baltimore_falsification"),
        "D": ("graphical_abstract", "spatial_accounting", "inventory_trends", "aq_null", "equity_baseline"),
    }
    for paper, names in expected.items():
        figures = root / "manuscript" / module.PAPERS[paper]["bundle"] / "figures"
        present = {p.name for p in figures.glob("paper*")}
        for name in names:
            for suffix in ("png", "pdf"):   # journals require a raster and a vector of each
                assert f"paper{paper}_{name}.{suffix}" in present, f"missing paper{paper}_{name}.{suffix}"


def test_each_bundle_is_self_sufficient() -> None:
    """A bundle must be zippable and submittable on its own: manuscript, cover letter, claim ledger,
    index, its own figures, and a bib byte-identical to the master."""
    root = Path(__file__).resolve().parents[1]
    module = _load_verifier(root)
    master_bib = (root / "manuscript/references.bib").read_bytes()
    for paper, spec in module.PAPERS.items():
        home = root / "manuscript" / spec["bundle"]
        assert (home / spec["tex"]).is_file(), f"{paper}: missing {spec['tex']}"
        for required in ("cover_letter.tex", "claims.csv", "INDEX.md", "references.bib"):
            assert (home / required).is_file(), f"{paper}: bundle missing {required}"
        assert (home / "references.bib").read_bytes() == master_bib, \
            f"{paper}: bundle references.bib has drifted from the master"
        assert list((home / "figures").glob("*.png")), f"{paper}: bundle has no figures"
        if spec.get("highlights"):
            assert (home / "highlights.txt").is_file(), f"{paper}: missing highlights.txt"
        # every figure the manuscript includes must resolve inside this bundle
        text = (home / spec["tex"]).read_text(encoding="utf-8")
        for stem in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", text):
            figure = home / "figures" / stem
            raster = figure if figure.suffix else figure.with_suffix(".png")
            assert raster.is_file(), f"{paper}: {stem} not inside the bundle"


def test_si_crossreferences_resolve_and_the_check_actually_fires() -> None:
    """The main text hard-codes SI numbers ("SI~S7", "Supplementary Table~S11") because the two documents
    compile separately and a \\ref cannot cross them. Inserting anything into the SI renumbers every later
    target, turning a correct citation into a confidently wrong one. Both failure modes must raise."""
    root = Path(__file__).resolve().parents[1]
    module = _load_verifier(root)
    spec = module.PAPERS["A"]
    text = (root / "manuscript" / spec["bundle"] / spec["tex"]).read_text(encoding="utf-8")

    module.si_crossref_check("A", spec, text)   # the real manuscript resolves

    # 1. An unregistered literal is caught. This is the class of defect that had the era-seam battery
    #    cited as "Supplementary Table S9", which is in fact the social-cost table.
    with pytest.raises(AssertionError, match="absent from"):
        module.si_crossref_check("A", spec, text + "\nsee Supplementary Table~S9 for the era seam.\n")

    # 2. A reference aimed at the wrong item is caught: table S1 is tab:xsource, not tab:ed_summary.
    original = module.SI_CROSSREFS["A"]["tables"]
    module.SI_CROSSREFS["A"]["tables"] = {1: "tab:ed_summary"}
    try:
        with pytest.raises(AssertionError, match="should be tab:ed_summary"):
            module.si_crossref_check(
                "A", spec, text.replace("Supplementary Table~S11", "Supplementary Table~S1"))
    finally:
        module.SI_CROSSREFS["A"]["tables"] = original


def test_evidence_digests_do_not_depend_on_line_endings() -> None:
    """A ledger digest must mean "this content", not "this content as checked out on my platform".

    Until 2026-08-22 these were raw file hashes, so a Linux checkout (LF) failed 28 of 41 claims that a
    Windows checkout (CRLF) passed, with no byte of content differing. That reads as data corruption and
    stops reproduction at the first command. Every evidence file must now hash identically either way.
    """
    root = Path(__file__).resolve().parents[1]
    module = _load_verifier(root)
    import csv

    checked = 0
    for spec in module.PAPERS.values():
        ledger = root / "manuscript" / spec["bundle"] / "claims.csv"
        with ledger.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                source = root / row["evidence_path"]
                lf = source.read_bytes().replace(b"\r\n", b"\n")
                for variant in (lf, lf.replace(b"\n", b"\r\n")):
                    with tempfile.NamedTemporaryFile(suffix=source.suffix, delete=False) as fh:
                        fh.write(variant)
                        temp = Path(fh.name)
                    try:
                        assert module.sha256(temp) == row["evidence_sha256"], (
                            f"{row['claim_id']}: {row['evidence_path']} hashes differently with "
                            "LF vs CRLF line endings")
                    finally:
                        temp.unlink()
                checked += 1
    assert checked == 41, f"expected 41 claims across the four ledgers, found {checked}"


def test_equity_baseline_reproduces_reported_values() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = spec_from_file_location("equity_baseline", root / "src/analysis/equity_baseline.py")
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.build().set_index("group")
    port, county = result.loc["port_adjacent"], result.loc["los_angeles_county"]
    assert (port.tracts, port.population) == (183, 729650)
    assert (county.tracts, county.population) == (2498, 9936690)
    assert round(port.population_weighted_tract_median_income_usd) == 84278
    assert round(county.population_weighted_tract_median_income_usd) == 89470
    assert round(port.black_share_pct, 1) == 11.9
    assert round(county.black_share_pct, 1) == 7.9
    assert round(port.mean_ces_score_percentile, 1) == 69.4
    assert round(county.mean_ces_score_percentile, 1) == 65.1
