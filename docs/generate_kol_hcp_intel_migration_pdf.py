#!/usr/bin/env python3
"""Generate PDF from docs/kol-hcp-intel-migration.md."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fpdf import FPDF

DOCS = Path(__file__).resolve().parent
MD_PATH = DOCS / "kol-hcp-intel-migration.md"
OUT_PATH = DOCS / "KOL_HCP_Intel_Migration_Spec.pdf"

MARGIN_L = 16
MARGIN_T = 20
MARGIN_R = 16
MARGIN_B = 24
LINE_H = 5.2
BODY = 9.5
SMALL = 8.5


def sanitize(text: str) -> str:
    replacements = {
        "\u2014": " - ",
        "\u2013": "-",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2194": "<->",
        "\u2022": "*",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a7": "Section ",
        "\u2026": "...",
        "\u251c": "|--",
        "\u2514": "`--",
        "\u2502": "|",
        "\u2500": "-",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Drop any remaining non-latin-1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")


def strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return sanitize(text.strip())


class SpecPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
        self.set_auto_page_break(auto=True, margin=MARGIN_B)

    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 7.5)
            self.set_text_color(110, 110, 110)
            self.cell(0, 5, "CHT Content Hub - KOL + HCP Intel Migration Spec", align="L")
            self.cell(0, 5, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(210, 210, 210)
            self.line(MARGIN_L, 14, 210 - MARGIN_R, 14)
            self.ln(5)
            self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "Confidential - Internal Architecture Plan", align="C")

    def _space(self, mm: float = 2.5) -> None:
        self.ln(mm)

    def _ensure(self, needed: float = 30) -> None:
        if self.get_y() + needed > self.page_break_trigger:
            self.add_page()

    def h1(self, title: str) -> None:
        self._ensure(20)
        self._space(3)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(25, 55, 95)
        self.multi_cell(0, 7, strip_md(title))
        self._space(2)
        y = self.get_y()
        self.set_draw_color(25, 55, 95)
        self.line(MARGIN_L, y, 210 - MARGIN_R, y)
        self._space(4)
        self.set_text_color(0, 0, 0)

    def h2(self, title: str) -> None:
        self._ensure(16)
        self._space(3)
        self.set_font("Helvetica", "B", 11.5)
        self.set_text_color(40, 70, 110)
        self.multi_cell(0, 6, strip_md(title))
        self._space(3)
        self.set_text_color(0, 0, 0)

    def h3(self, title: str) -> None:
        self._ensure(12)
        self._space(2)
        self.set_font("Helvetica", "B", 10.5)
        self.multi_cell(0, 5.5, strip_md(title))
        self._space(2)

    def para(self, text: str) -> None:
        if not text.strip():
            return
        self.set_font("Helvetica", "", BODY)
        self.multi_cell(0, LINE_H, strip_md(text))
        self._space(3)

    def quote(self, text: str) -> None:
        self._ensure(12)
        self.set_font("Helvetica", "I", BODY)
        self.set_fill_color(248, 248, 252)
        x = self.l_margin + 4
        self.set_x(x)
        self.multi_cell(self.epw - 8, LINE_H, strip_md(text), fill=True)
        self._space(3)
        self.set_font("Helvetica", "", BODY)

    def bullet(self, text: str) -> None:
        self.set_font("Helvetica", "", BODY)
        indent = 6
        self.set_x(self.l_margin + indent)
        self.multi_cell(self.epw - indent, LINE_H, f"-  {strip_md(text)}")
        self._space(1.5)

    def code_block(self, lines: list[str]) -> None:
        self._ensure(max(20, len(lines) * 4.8 + 4))
        self._space(2)
        self.set_font("Courier", "", SMALL)
        self.set_fill_color(245, 245, 245)
        for line in lines:
            self.set_x(self.l_margin)
            safe = sanitize(line.replace("\t", "    "))[:120]
            self.cell(self.epw, 4.8, f"  {safe}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self._space(4)
        self.set_font("Helvetica", "", BODY)

    def table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        if ncols == 0:
            return
        widths = [self.epw / ncols] * ncols
        # Wider first column for 2-col tables
        if ncols == 2:
            widths = [self.epw * 0.38, self.epw * 0.62]
        elif ncols == 3:
            widths = [self.epw * 0.28, self.epw * 0.36, self.epw * 0.36]
        elif ncols == 4:
            widths = [self.epw * 0.22, self.epw * 0.26, self.epw * 0.26, self.epw * 0.26]

        line_h = 4.8
        for ri, row in enumerate(rows):
            while len(row) < ncols:
                row.append("")
            cells = [strip_md(c) for c in row]
            self._ensure(line_h * 4)
            x0 = self.l_margin
            y0 = self.get_y()
            max_lines = 1
            for text, w in zip(cells, widths):
                n = self.multi_cell(w, line_h, text, dry_run=True, output="LINES")
                max_lines = max(max_lines, len(n))
            row_h = max_lines * line_h + 2
            if y0 + row_h > self.page_break_trigger:
                self.add_page()
                y0 = self.get_y()
            x = x0
            self.set_font("Helvetica", "B" if ri == 0 else "", SMALL)
            for text, w in zip(cells, widths):
                self.set_xy(x, y0)
                self.multi_cell(w, line_h, text, border=1)
                x += w
            self.set_xy(x0, y0 + row_h)
        self._space(4)
        self.set_font("Helvetica", "", BODY)


def parse_markdown(text: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            blocks.append(("hr", None))
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", code))
            i += 1
            continue
        if line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
            i += 1
            continue
        if line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
            i += 1
            continue
        if line.startswith("### "):
            blocks.append(("h3", line[4:].strip()))
            i += 1
            continue
        if line.startswith("> "):
            blocks.append(("quote", line[2:].strip()))
            i += 1
            continue
        if line.startswith("|") and "|" in line[1:]:
            table_rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                if re.match(r"^\|\s*[-:]+", lines[i]):
                    i += 1
                    continue
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            blocks.append(("table", table_rows))
            continue
        if re.match(r"^[-*] \[[ x]\] ", line):
            blocks.append(("bullet", line[6:].strip()))
            i += 1
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append(("bullet", line[2:].strip()))
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        para_lines = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", ">", "|", "-", "*", "```")):
            para_lines.append(lines[i].strip())
            i += 1
        blocks.append(("para", " ".join(para_lines)))
    return blocks


def render(pdf: SpecPDF, blocks: list[tuple[str, object]]) -> None:
    for kind, content in blocks:
        if kind == "hr":
            pdf._space(2)
            continue
        if kind == "h1":
            pdf.h1(str(content))
        elif kind == "h2":
            pdf.h2(str(content))
        elif kind == "h3":
            pdf.h3(str(content))
        elif kind == "para":
            pdf.para(str(content))
        elif kind == "quote":
            pdf.quote(str(content))
        elif kind == "bullet":
            pdf.bullet(str(content))
        elif kind == "code":
            pdf.code_block(content)  # type: ignore[arg-type]
        elif kind == "table":
            pdf.table(content)  # type: ignore[arg-type]


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    blocks = parse_markdown(md)

    pdf = SpecPDF()
    pdf.add_page()
    pdf._space(28)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 10, "CHT Content Hub\nKOL + HCP Intel\nMigration Spec", align="C")
    pdf._space(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6.5,
        f"Generated: {date.today().strftime('%B %d, %Y')}\n\n"
        "Backend + data migration from chm-mediahub\n"
        "Frontend rebuild - API contracts only",
        align="C",
    )
    pdf._space(14)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5.5,
        "Source: docs/kol-hcp-intel-migration.md\n"
        "Target: zero KOL and HCP Intel ownership in MediaHub after cutover.",
        align="C",
    )

    pdf.add_page()
    render(pdf, blocks)
    pdf.output(str(OUT_PATH))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
