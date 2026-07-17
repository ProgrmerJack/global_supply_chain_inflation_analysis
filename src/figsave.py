"""Shared figure writer for manuscript display items.

Journals require at least 300-dpi raster and prefer vector line art, so every figure is
emitted twice under the same stem: a 300-dpi PNG and a matching PDF. The publication
verifier checks for that raster/vector pair, so writing only a PNG fails the package.
"""

from pathlib import Path

import matplotlib.pyplot as plt


def save_figure(fig, png_path, dpi: int = 300, close: bool = True) -> Path:
    """Write ``fig`` to ``png_path`` at ``dpi`` and to the matching ``.pdf``."""
    png = Path(png_path)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(png.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    if close:
        plt.close(fig)
    return png


def demo() -> None:
    """Self-check: a saved figure must leave both a raster and a vector file behind."""
    import tempfile

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    with tempfile.TemporaryDirectory() as tmp:
        out = save_figure(fig, Path(tmp) / "probe.png")
        assert out.is_file(), "PNG was not written"
        assert out.with_suffix(".pdf").is_file(), "vector PDF was not written"
        assert out.stat().st_size > 0 and out.with_suffix(".pdf").stat().st_size > 0
    print("figsave OK: raster and vector both written")


if __name__ == "__main__":
    demo()
