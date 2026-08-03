from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re


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
