"""Prepare FORECAST industry energy-demand data for the NRW workflow.

The script reads the raw FORECAST energy-demand workbook from
`data/forecast_industry/industrial_energy_demand_forecast.xlsx`, translates the
relevant labels to the naming used in the downstream pipeline, performs basic
validation, optionally converts hydrogen feedstock demand to methanol demand
for the MtO route, and exports scenario-specific CSV files.

Outputs are written in the layout consumed by
`build_industrial_energy_demand_per_node_forecast.py`:
`data/forecast_industry/<scenario>/energy_demand.csv`.
An additional Excel workbook with one sheet per scenario is also written for
inspection.

Log:
-------
Version:[0.1]
Author:[Khaled Al-Dabbas @ Fraunhofer ISI]
Date:[06.11.2025]

Version:[0.2]
Author:[Thorben Steiger @ Fraunhofer ISI]
Date:[28.01.2026]
  -integrated MtO route option, H2 -> Methanol (chemical feedstock)
"""


import pandas as pd
from pathlib import Path
import os
import warnings

# =============================================================================
# 0. MtO ROUTE CONFIGURATION
# -----------------------------------------------------------------------------
# True  = Convert annual H2 amount into Methanol amount (TWh).
# False = Use H2.
# =============================================================================

MTO_ROUTE = True
SEC = 22.5                       # 22,5 GJ H2 for producing 1 ton of  Methanol, id_process 72 (GJ_H2 / t_methanol)
LHV_METHANOL = 5.53 / 1e6        # LHV Methanol in TWh/t,  19.9 MJ/kg (or 5.53 GJ/t) converted to TWh/t by dividing by 1e6 (TWh_methanol / t_methanol)
t_H2_to_t_METHANOL = 3.6 * 1e6   # 1 TWh = 3,6 * 10^6 GJ, 10^6 gets cancelled with 10^6 in LHV_METHANOL

TWh_H2_to_TWh_METHANOL = LHV_METHANOL * t_H2_to_t_METHANOL / SEC   # conversion factor

## 1 TWh_H2 -> 160,000 t methanol -> 0.885 TWh_methanol

# =============================================================================
# 1. TRANSLATION DICTIONARY
# -----------------------------------------------------------------------------
# Maps German column names, sector/process labels, and energy carriers
# to English equivalents. Used both for column headers and cell values.
# =============================================================================

translate = {
    # --- Column headers ---
    "Szenario": "Scenario",
    "Land": "Country",
    "Prozess": "Process",
    "Sektor": "Sector",
    "Subsektor": "Subsector",
    "Einheit": "Unit",
    "Energieträger": "Energy_carrier",
    "Anwendung": "Application",

    # --- Energy carriers ---
    "Strom": "Electricity",
    "Heizöl": "Fuel oil",
    "Kohle": "Coal",
    "Erdgas": "Natural gas",
    "Andere fossile": "Other fossil",
    "Müll nicht erneuerbar": "Waste non-RES",
    "Biomasse": "Biomass",
    "Fernwärme": "District heating",
    "Solarenergie": "Solar energy",
    "Umgebungswärme": "Ambient heat",
    "Übrige, erneuerbar": "Other RES",
    "Naphtha": "Naphtha",
    "Wasserstoff": "Hydrogen",
    "EE-Methan": "EE-methane",

    # --- Industrial processes ---
    "Oxygenstahl - Hochofen und Konverter": "Blast furnace and converter",
    "Elektrostahl - EAF": "Electric arc furnace (EAF)",
    "Walzstahl": "Rolled steel",
    "Direkte Reduktion": "Direct reduction",
    "Aluminium primär": "Aluminum (primary)",
    "Aluminium sekundär": "Aluminum (secondary)",
    "Papier": "Paper",
    "Zellstoff - Verfahren": "Chemical pulp process",
    "Holzstoff - Verfahren": "Mechanical pulp process",
    "Altpapierstoff": "Recovered fibers",
    "Behälterglas": "Container glass",
    "Flachglas": "Flat glass",
    "Klinker Brennen (trocken)": "Clinker calcination (dry process)",
    "Kalkbrennen": "Lime burning",
    "Ammoniak": "Ammonia",
    "Chlor, Diaphragma": "Chlorine (diaphragm process)",
    "Chlor, Membran": "Chlorine (membrane process)",
    "Chlor, Amalgan": "Chlorine (mercury process)",
    "Ethylen": "Ethylene",
    "Methanol": "Methanol",
    "Behälterglas Elektroschmelzofen": "Container glass (electric furnace)",
    "Flachglas Elektroschmelzofen": "Flat glass (electric furnace)",
    "Low-carbon Zement - 50%": "Low-carbon cement (50%)",
    "Methanol H2": "Methanol (H₂ route)",
    "Ammonia H2": "Ammonia (H₂ route)",
    "Ethylen Methanol-Route": "Ethylene (methanol-based route)",
    "DR RES H2 + EAF": "Direct reduction (H₂) + EAF",

    # --- Subsectors (AGEB classification) ---
    "Gewinnung von Steinen und Erden, sonst. Bergbau": "Quarrying of stone and earth; other mining",
    "Ernährung und Tabak": "Food and tobacco",
    "Papiergewerbe": "Paper industry",
    "Grundstoffchemie": "Basic chemicals",
    "Sonstige chemische Industrie": "Other chemical industry",
    "Gummi- u. Kunststoffwaren": "Rubber and plastic products",
    "Glas u. Keramik": "Glass and ceramics",
    "Verarbeitung v. Steine u. Erden": "Processing of stone and earth (non-metallic mineral processing)",
    "Metallerzeugung": "Basic metals (metal production)",
    "NE-Metalle, -gießereien": "Non-ferrous metals and foundries",
    "Metallbearbeitung": "Fabricated metal products (metalworking)",
    "Maschinenbau": "Machinery and equipment (mechanical engineering)",
    "Fahrzeugbau": "Vehicle manufacturing (motor vehicles and transport equipment)",
    "Sonstige Wirtschaftszweige": "Other economic sectors",
    "Raffinerien": "Refineries",

    # --- Applications ---
    "Prozesswärme Dampf": "Process heat (steam)",
    "Energiebilanz-Kalibrierung": "Energy balance calibration",
    "Prozesswärme Industrieöfen": "Process heat (industrial furnaces)",
    "Raumwärme": "Space heating",
    "Prozesskälte": "Process cooling",
    "Querschnittstechniken": "Mechanical and other electricity use",
    "Raumkühlung": "Space cooling",
    "Elektrolyse": "Electrolysis (aluminium smelting)",
    "CCS": "Carbon capture and storage",
    "Rohstoffbedarf": "Raw material (feedstock) demand",
}

# =============================================================================
# 2. CONFIGURATION AND FILE PATHS
# =============================================================================
# Target sheet name and relative column in the input Excel file
TARGET_SHEET = None #"forecast_regio_nachfrage"  # Set None to load first sheet
SCEN_COL = "Scenario"                      # Column identifying scenarios

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd().resolve()
# Define input and output paths used by the FORECAST preprocessing workflow
xlsx_infile  = ROOT / "data" / "forecast_industry" / "industrial_energy_demand_forecast.xlsx"
xlsx_outfile = ROOT / "data" / "forecast_industry" / "industrial_energy_demand_by_scenario.xlsx"
csv_outdir   = ROOT / "data" / "forecast_industry"
# Validate input and ensure output folders exist
if not xlsx_infile.exists():
    raise FileNotFoundError(f" Input Excel not found: {xlsx_infile}")
# Ensure output directories exist
xlsx_outfile.parent.mkdir(parents=True, exist_ok=True)
# Ensure CSV output directory exists
csv_outdir.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 3. READ EXCEL FILE
# =============================================================================
# Get list of available sheet names
xls = pd.ExcelFile(xlsx_infile, engine="openpyxl")
available_sheets = xls.sheet_names
print(f"Available sheets: {available_sheets}")

if TARGET_SHEET in available_sheets:
    print(f" Reading sheet: '{TARGET_SHEET}'")
    df = pd.read_excel(xls, sheet_name=TARGET_SHEET)
else:
    warnings.warn(
        f"Sheet '{TARGET_SHEET}' not found. "
        f"Using first sheet '{available_sheets[0]}' instead.",
        UserWarning
    )
    df = pd.read_excel(xls, sheet_name=available_sheets[0])

# =============================================================================
# 4. TRANSLATION AND CLEANUP
# =============================================================================
# Strip whitespace from column names for better matching
df.columns = [str(c).strip() for c in df.columns]
# Rename columns using the translation dictionary
df.rename(columns=translate, inplace=True)
# Translate values in key columns
for col in ["Energy_carrier", "Subsector", "Application"]:
    if col in df.columns:
        df[col] = df[col].replace(translate)

# =============================================================================
# 5. VALIDATION SECTION
# =============================================================================
print("\n Starting forecast industry data validation...\n")
# ----- Identify numeric year columns -----
value_cols = [c for c in df.columns if str(c).isdigit()]

if not value_cols:
    warnings.warn("No year columns detected (expected 4-digit headers like 2020..2100).", UserWarning)
else:
  # Ensure numeric dtype for year columns in case they were read as strings.
  df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
  print(f"Detected numeric columns: {len(value_cols)} years ({value_cols[0]}..{value_cols[-1]})")

  # ----- validate missing values -----
  # calculate percentage of missing values across all numeric cells
  missing_perc = df[value_cols].isna().mean().mean() * 100
  print(f"Missing value share across numeric cells: {missing_perc:.2f}%")

  # ----- validate negative values -----
  # find any negative values in value_cols
  neg_positions = (df[value_cols] < 0)
  # find rows with any negative values
  neg_rows = neg_positions.any(axis=1)
  num_neg = neg_rows.sum()
  print(f"Negative entries: {num_neg:,}")
  if num_neg:
      print("Warning: Showing up to 5 rows with negatives:")
      for idx, row in df.loc[neg_rows].head(5).iterrows():
          bad_years = [c for c in value_cols if row[c] < 0]
          print(f"Row {idx}: negative in years {bad_years}")

  # ----- validate zero-only rows -----
  # Count rows where all detected year columns are zero.
  zero_only_rows = (df[value_cols].sum(axis=1) == 0).sum()
  print(f"Rows with all zero values across numeric columns: {zero_only_rows:,}")

# --- Scenario presence check ---
# Warn if multiple scenarios are detected
if SCEN_COL in df.columns:
  unique_scenarios = df[SCEN_COL].dropna().unique()
  if len(unique_scenarios) > 1:
      warnings.warn(
          f"The dataset contains {len(unique_scenarios)} scenarios "
          f"({', '.join(map(str, unique_scenarios[:5]))}"
          f"{'...' if len(unique_scenarios) > 5 else ''}). "
          "Make sure you filter or import only the relevant scenario before analysis.",
          UserWarning
      )
  else:
      print(f" Single scenario detected: {unique_scenarios[0]}")
else:
  print("Warning: No 'Scenario' column found in DataFrame.")

# --- MTO route adjustment ---
if MTO_ROUTE:
    required_cols = {"Energy_carrier", "Application"}
    missing = required_cols - set(df.columns)
    if missing:
        warnings.warn(
            f"MtO route requested (MTO_ROUTE=True) but missing columns: {sorted(missing)}. Skipping MtO conversion.",
            UserWarning,
        )
    elif not value_cols:
        warnings.warn(
            "MtO route requested (MTO_ROUTE=True) but no numeric year columns were detected. Skipping MtO conversion.",
            UserWarning,
        )
    else:
        app_target = "Raw material (feedstock) demand"

        # Boolean mask for rows to convert
        mto_mask = (df["Energy_carrier"] == "Hydrogen") & (df["Application"] == app_target)
        n_rows = int(mto_mask.sum())

        # Print year sums before conversion for the feedstock application only.
        h2_before = df.loc[
            (df["Energy_carrier"] == "Hydrogen") & (df["Application"] == app_target),
            value_cols,
        ].sum(numeric_only=True)
        meoh_before = df.loc[
            (df["Energy_carrier"] == "Methanol") & (df["Application"] == app_target),
            value_cols,
        ].sum(numeric_only=True)

        print("\n MtO route adjustment (H2 -> Methanol) enabled.")
        print(f" Rows to convert (Energy_carrier=Hydrogen & Application={app_target!r}): {n_rows:,}")
        print(" Yearly sums BEFORE conversion (Application = feedstock):")
        print("  Hydrogen:")
        print(h2_before)
        print("  Methanol:")
        print(meoh_before)

        if n_rows == 0:
            print(" No matching rows found. Nothing to convert.")
        else:
            # Convert numeric year values
            df.loc[mto_mask, value_cols] = df.loc[mto_mask, value_cols] * TWh_H2_to_TWh_METHANOL

            # Rename carrier in converted rows
            df.loc[mto_mask, "Energy_carrier"] = "Methanol"

            # Print year sums after conversion.
            h2_after = df.loc[
                (df["Energy_carrier"] == "Hydrogen") & (df["Application"] == app_target),
                value_cols,
            ].sum(numeric_only=True)
            meoh_after = df.loc[
                (df["Energy_carrier"] == "Methanol") & (df["Application"] == app_target),
                value_cols,
            ].sum(numeric_only=True)

            print("\n Yearly sums AFTER conversion (Application = feedstock):")
            print("  Hydrogen:")
            print(h2_after)
            print("  Methanol:")
            print(meoh_after)

            # Show the methanol increase caused by the conversion.
            delta_meoh = (meoh_after - meoh_before)
            print("\n Added Methanol due to conversion (Methanol_after - Methanol_before):")
            print(delta_meoh)

print("\n Validation completed successfully.")

# =============================================================================
# 6. EXPORT SECTION
# -----------------------------------------------------------------------------
# Export one Excel sheet per scenario and one CSV per scenario in the
# Snakemake input layout under data/forecast_industry/<scenario>/.
# =============================================================================
# Helper function to create Excel-safe sheet names
def safe_sheet(name: str) -> str:
    # Replace invalid characters for Excel sheet names
    """Excel-safe sheet name (no illegal characters)."""
    invalid = '[]:*?/\\'
    for ch in invalid:
        name = str(name).replace(ch, '_')
    return str(name)[:31] or "Sheet"

# Determine scenario list
if SCEN_COL in df.columns and df[SCEN_COL].notna().any():
    scenarios = sorted(df[SCEN_COL].dropna().astype(str).unique())
else:
    scenarios = ["All"]

# --- Write multi-sheet Excel ---
with pd.ExcelWriter(xlsx_outfile, engine="openpyxl") as writer:
    for s in scenarios:
        df_s = df if s == "All" else df[df[SCEN_COL].astype(str) == s]
        df_s.to_excel(writer, sheet_name=safe_sheet(s), index=False)
print(f" Wrote Excel with {len(scenarios)} sheet(s): {xlsx_outfile}")

# --- Write per-scenario CSVs in the Snakemake layout ---
for s in scenarios:
    df_s = df if s == "All" else df[df[SCEN_COL].astype(str) == s]
    scenario_dir = csv_outdir / str(s)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    csv_out = scenario_dir / "energy_demand.csv"
    df_s.to_csv(csv_out, index=False, encoding="utf-8")
    print(f" Wrote CSV: {csv_out}")

print("\n Export completed successfully.")
