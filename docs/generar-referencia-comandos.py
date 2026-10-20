"""Genera el PDF desde Markdown canónico. Requiere reportlab (solo documentación).

Desde la raíz: python docs/generar-referencia-comandos.py
No carga configuración ni importa la aplicación.
"""
from pathlib import Path
import hashlib
import html
import re
import textwrap

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    Preformatted,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "docs/comandos-whatsapp.md", ROOT / "docs/operacion.md"]
OUTPUT = ROOT / "output/pdf/GPS_EMI-referencia-comandos.pdf"
styles = getSampleStyleSheet()
styles.add(ParagraphStyle("BodyDoc", fontName="Helvetica", fontSize=9,
                         leading=13, spaceAfter=7))
styles.add(ParagraphStyle("CellDoc", parent=styles["BodyDoc"], fontSize=8,
                         leading=11, spaceAfter=0))
styles.add(ParagraphStyle("CodeDoc", fontName="Courier", fontSize=7,
                         leading=10, spaceAfter=9))
styles["Heading1"].fontSize = 18
styles["Heading1"].leading = 22
styles["Heading2"].spaceBefore = 13
styles["Heading1"].keepWithNext = True
styles["Heading2"].keepWithNext = True


def inline(value):
    value = html.escape(value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)


def blocks(source):
    lines = source.read_text(encoding="utf-8").splitlines()
    result = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            code = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                # Corte visual señalado: no es continuación ejecutable del shell.
                parts = textwrap.wrap(lines[index], width=104, replace_whitespace=False,
                                      drop_whitespace=False) or [""]
                code.extend([parts[0]] + ["    " + p for p in parts[1:]])
                index += 1
            result.append(Preformatted("\n".join(code), styles["CodeDoc"]))
            index += 1
            continue
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = lines[index].strip().strip("|").split("|")
                if not all(re.fullmatch(r"[\s:-]+", c) for c in cells):
                    rows.append([Paragraph(inline(c.strip()), styles["CellDoc"]) for c in cells])
                index += 1
            widths = [164, 351] if len(rows[0]) == 2 else [515 / len(rows[0])] * len(rows[0])
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf4")),
                ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#b8c5cf")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            result.extend([table, Spacer(1, 9)])
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            result.append(Paragraph(inline(line.lstrip("# ")),
                                    styles["Heading1" if level == 1 else "Heading2"]))
            index += 1
            continue
        if re.match(r"^\d+\.\s", line):
            result.append(Paragraph(inline(line), styles["BodyDoc"]))
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip():
            if lines[index].startswith(("#", "|", "```")):
                break
            paragraph.append(lines[index].removeprefix("> "))
            index += 1
        result.append(Paragraph(inline(" ".join(paragraph)), styles["BodyDoc"]))
    return result


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#526575"))
    canvas.drawString(40, 24, "Referencia documental | código contrastado: a8f3f24")
    canvas.drawRightString(555, 24, str(doc.page))
    canvas.restoreState()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = "; ".join(f"{p.name} SHA256={hashlib.sha256(p.read_bytes()).hexdigest()}"
                         for p in SOURCES)
    story = [
        Paragraph("Referencia de comandos y operación", styles["Title"]),
        Paragraph("Edición documental · 20 de octubre de 2026", styles["BodyDoc"]),
        Paragraph("Sistema existente; no acredita una versión desplegada. Ejemplos "
                  "sintéticos. Se conservan nombres técnicos del contrato, sin afirmar "
                  "afiliación ni autorización de terceros.", styles["BodyDoc"]),
        Paragraph("Contenido completo de docs/comandos-whatsapp.md y docs/operacion.md. "
                  "Los enlaces se consultan en esos archivos. Los bloques largos se "
                  "ajustan visualmente: copiar comandos desde Markdown. Las cifras de "
                  "pruebas conservan la fecha de su fuente.", styles["BodyDoc"]),
        Paragraph("Regenerar desde la raíz con Python y ReportLab: "
                  "python docs/generar-referencia-comandos.py. "
                  "Las huellas de ambas fuentes están en los metadatos del PDF.",
                  styles["BodyDoc"]),
        PageBreak(),
    ]
    for number, source in enumerate(SOURCES):
        if number:
            story.append(PageBreak())
        story.extend(blocks(source))
    SimpleDocTemplate(str(OUTPUT), pagesize=(595, 842), rightMargin=40,
                      leftMargin=40, topMargin=40, bottomMargin=43,
                      title="Referencia de comandos y operación",
                      author="Documentación técnica", subject=manifest).build(
                          story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
