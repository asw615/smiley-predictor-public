import csv
import os
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def write_csv(path: Path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, path)


def normalize_text(value) -> str:
    return " ".join(str(value or "").split()).strip()


def column_letters(cell_ref: str) -> str:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise ValueError(f"Could not parse cell reference: {cell_ref}")
    return match.group(1)


def cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    value_node = cell.find("x:v", NS)
    inline_node = cell.find("x:is", NS)

    if cell_type == "s" and value_node is not None:
        return shared_strings[int(value_node.text)]
    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text.text or "" for text in inline_node.iterfind(".//x:t", NS))
    if value_node is not None:
        return value_node.text
    return None


def load_xlsx_rows(path: Path):
    with ZipFile(path) as workbook:
        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for entry in shared_root.findall("x:si", NS):
                shared_strings.append(
                    "".join(text.text or "" for text in entry.iterfind(".//x:t", NS))
                )

        sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet2.xml"))
        sheet_rows = []
        for row in sheet_root.findall(".//x:sheetData/x:row", NS):
            values_by_col = {}
            for cell in row.findall("x:c", NS):
                values_by_col[column_letters(cell.attrib["r"])] = cell_value(
                    cell, shared_strings
                )
            sheet_rows.append(values_by_col)

    ordered_columns = sorted(sheet_rows[0].keys(), key=lambda value: (len(value), value))
    headers = [sheet_rows[0][column] for column in ordered_columns]

    rows = []
    for row in sheet_rows[1:]:
        rows.append({header: row.get(column) for header, column in zip(headers, ordered_columns)})
    return headers, rows
