#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Convert the industry carrier mapping workbook to CSV.

This helper script reads `data/forecast_industry/mapping.xlsx` and writes the
same table to `data/forecast_industry/mapping.csv` for downstream use in the
FORECAST industry demand pipeline.
"""

from pathlib import Path

import pandas as pd


# Root directory:
# - If run as a script: go two levels up from this file.
# - If run interactively: use current working directory.
try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd().resolve()


# Input and output paths for the mapping conversion helper.
xlsx_infile = ROOT / "data" / "forecast_industry" / "mapping.xlsx"
csv_outdir = ROOT / "data" / "forecast_industry"

csv_outdir.mkdir(parents=True, exist_ok=True)

xls = pd.ExcelFile(xlsx_infile, engine="openpyxl")
df_scen = pd.read_excel(xls)
df_scen.to_csv(csv_outdir / "mapping.csv", index=False, encoding="utf-8")
