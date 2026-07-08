#!/usr/bin/env python3
"""Generate PDF from docs/kol-network-api-spec.md."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

DOCS = Path(__file__).resolve().parent
MD_PATH = DOCS / "kol-network-api-spec.md"
OUT_PATH = DOCS / "KOL_Network_API_Spec.pdf"

# Reuse renderer from migration PDF generator
sys.path.insert(0, str(DOCS))
from generate_kol_hcp_intel_migration_pdf import (  # noqa: E402
    SpecPDF,
    parse_markdown,
    render,
    strip_md,
)

HEADER = "CHT Content Hub - KOL Network Public API Spec"


class KolNetworkPDF(SpecPDF):
    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 7.5)
            self.set_text_color(110, 110, 110)
            self.cell(0, 5, HEADER, align="L")
            self.cell(0, 5, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(210, 210, 210)
            self.line(16, 14, 210 - 16, 14)
            self.ln(5)
            self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "Internal - CHT Integration Reference", align="C")


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    blocks = parse_markdown(md)

    pdf = KolNetworkPDF()
    pdf.add_page()
    pdf._space(32)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 10, "KOL Network\nPublic API Spec", align="C")
    pdf._space(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6.5,
        f"Generated: {date.today().strftime('%B %d, %Y')}\n\n"
        "Content Hub producer API for CHT /kol-network\n"
        "Dev: devhub.communityhealth.media",
        align="C",
    )
    pdf._space(14)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5.5,
        strip_md("Source: docs/kol-network-api-spec.md\n"
                 "Implement against KOL_BASE_URL (catalog stays on MediaHub until cutover)."),
        align="C",
    )

    pdf.add_page()
    render(pdf, blocks)
    pdf.output(str(OUT_PATH))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
