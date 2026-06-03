#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build industrial energy demand per node from FORECAST (simple, PyPSA-Eur style).

Pipeline (kept simple, step-logged)
1) Load inputs (FORECAST wide, region map, mapping rules)
2) Parse planning_horizons (single int or list[int])
3) Apply carrier rules (first-match-wins)
4) Map regions
5) Prune to essential cols
6) Aggregate to pypsa_region (still wide by year)
7) For each requested year:
   7.1) Validate totals BEFORE pivot
   7.2) Pivot to node  carrier wide
   7.3) Validate totals AFTER pivot
   7.4) Export CSV (reuse single-year path; year replaced/inserted for multi-year)
"""

import logging, re
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# Optional helper from your repo (for real Snakemake runs)

from scripts._helpers import configure_logging, set_scenario_config

# ---------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Canonical column order in the final file
DEMAND_COLS = [
    "Energy_carrier",
    "Sector",
    "Subsector",
    "Application",
]
ENERGY_CARRIERS = [
    "electricity",
    "coal",
    "coke",
    "solid biomass",
    "methane",
    "hydrogen",
    "low-temperature heat",
    "naphtha",
    "ammonia",
    "methanol",
    "process emission",
    "process emission from feedstock",
    "oil", # new implementation for pypsa-nrw
]
PROCESS_EMISSION_CARRIERS = [
    "process emission",
    "process emission from feedstock",
]
TARGET_CARRIERS = ENERGY_CARRIERS + PROCESS_EMISSION_CARRIERS
NODE_COL = "TWh/a (MtCO2/a)"
YEAR_MIN, YEAR_MAX = 1900, 2100


def detect_year_columns(df: pd.DataFrame) -> list[str]:
    years = []
    for c in df.columns:
        s = str(c)
        if s.isdigit() and len(s) == 4:
            y = int(s)
            if YEAR_MIN <= y <= YEAR_MAX:
                years.append(s)
    return sorted(years, key=int)


def _force_numeric(df: pd.DataFrame) -> pd.DataFrame:
    # Coerce object columns to numeric; leave numeric columns as-is
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out

NORM  = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
CANON = {NORM(c): c for c in TARGET_CARRIERS}
def canon(x):  # map any spelling to the canonical carrier if possible
    return CANON.get(NORM(x), x)


def proportional_overlay(source, target, source_id, target_id):
    """
    Allocate source-level quantities to target regions proportional to
    area overlap.

    Parameters
    ----------
    source : gpd.GeoDataFrame
        Source polygons with attributes to allocate.
    target : gpd.GeoDataFrame
        Target polygons (e.g. PyPSA regions).
    source_id : str
        Column name identifying each source polygon.
    target_id : str
        Column name identifying each target polygon.

    Returns
    -------
    gpd.GeoDataFrame
        Target-level attributes after proportional allocation.
    """
    src = source.to_crs(3857)
    trg = target.to_crs(3857)

    # compute source area per polygon
    src["area_src"] = src.geometry.area

    # intersection
    ov = gpd.overlay(trg, src, how="intersection", keep_geom_type=True)

    # compute intersection share relative to the source polygon
    ov["area_int"] = ov.geometry.area
    ov["share"] = ov["area_int"] / ov["area_src"]

    # identify numeric columns *from source* only
    numeric_cols = (
        ov.select_dtypes(include=["number"])
          .columns.difference(
              {target_id, source_id, "area_src", "area_int", "share"}
          )
    )

    # scale only source attributes
    ov[numeric_cols] = ov[numeric_cols].mul(ov["share"], axis=0)

    # Drop helper area columns
    ov = ov.drop(columns=["area_src", "area_int", "share"], errors="ignore")

    # collapse into target regions
    out = ov.dissolve(target_id, aggfunc="sum")

    return out


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_industrial_energy_demand_per_node_forecast",    
            industry_scenario="Orientierungsszenario_Strom",
            clusters="adm",
            planning_horizons="2035",
            run="forecast-co2-pipelines-min-ccs",
            configfiles=["config/config.nrw-workshop.yaml"],
        )
    
    configure_logging(snakemake)  # pylint: disable=E0606
    set_scenario_config(snakemake)
    
    config_forecast = snakemake.params.get("forecast_industry", {})

    if not logger.handlers:
      logging.basicConfig(
          level=logging.INFO,  
          format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
      )
    logger.setLevel(logging.DEBUG)  
    logger.info("[Debug] Effective log level = %s", logging.getLevelName(logger.getEffectiveLevel()))

    # ------------------ Step 1: Load ------------------
    logger.info("[Step 1] Load inputs")
    nuts3_shapes = gpd.read_file(snakemake.input.nuts3_shapes)
    regions = gpd.read_file(snakemake.input.regions)
    ied_forecast = pd.read_csv(snakemake.input.industrial_energy_demand_forecast, index_col=0) # TWh p.a.
    ipe_forecast = pd.read_csv(snakemake.input.industrial_process_emissions_forecast) # Mt p.a.

    carrier_mapping = pd.read_csv(snakemake.input.carrier_mapping).dropna(subset=["pypsa_carrier"])
    carrier_mapping = carrier_mapping[DEMAND_COLS + ["pypsa_carrier"]]

    # Settings
    year = snakemake.wildcards.planning_horizons
    current_electricity_year = str(config_forecast.get("current_electricity_year", 2021))
    strict = config_forecast.get("strict_industry_validation", True)

    # ------------------ Step 2: planning_horizons & years ------------------
    year_cols = detect_year_columns(ied_forecast)
    param_cols = [c for c in ied_forecast.columns if c not in year_cols]

    if not year_cols:
        raise ValueError("No 4-digit year columns found in FORECAST table.")
    missing = not (year in year_cols)
    if missing:
        avail = f"{year_cols[:10]}{'...' if len(year_cols) > 10 else ''}"
        raise ValueError(
            f"Requested planning_horizons not in data: {missing}. Available: {avail}"
        )
    
    ied_forecast = ied_forecast[param_cols + [current_electricity_year, year]]
    # Process emissions only need the specific year, not current_electricity_year
    ipe_cols = [c for c in param_cols if c in ipe_forecast.columns]
    ipe_forecast = ipe_forecast[ipe_cols + [year, "latitude", "longitude"]]

    # ------------------ Step 4: Apply carrier mapping ------------------
    # Map using carrier_mapping
    df_map_car = ied_forecast.merge(
        carrier_mapping,
        on=DEMAND_COLS,
        how="left",
        validate="m:1",
    )
    ipe_forecast = ipe_forecast.merge(
        carrier_mapping,
        on=DEMAND_COLS,
        how="left",
        validate="m:1",
    )
    
    # Split to year and current_electricity_year
    df_today = df_map_car[["Region", "pypsa_carrier", current_electricity_year]].copy()
    df_today = df_today.groupby(
        ["Region", "pypsa_carrier"], as_index=False
    )[current_electricity_year].sum()
    # Only keep elecricity
    df_today = df_today[df_today["pypsa_carrier"] == "electricity"].set_index("Region")

    df_map_car = df_map_car.drop(columns=[current_electricity_year])

    # ------------------ Step 5 ------------------
    logger.info("[Step 5] Prune to essential columns (%s)", year)
    keep = [
        "Country",
        "Subsector",
        "Application",
        "Energy_carrier",
        "Region",
        "pypsa_carrier",
        year,
    ]
    keep = [c for c in keep if c in df_map_car.columns]

    df_pruned = df_map_car[keep].copy()
    df_pruned["pypsa_carrier"] = df_pruned["pypsa_carrier"].map(canon)

    # ------------------ Step 6 ------------------
    logger.info("[Step 6] Aggregate to (wide by year %s)", year)
    group_keys = [
        k
        for k in [
            "Country",
            "Region",
            "pypsa_carrier",
            "Subsector",
            "Application",
        ]
        if k in df_pruned.columns
    ]
    df_region_wide = df_pruned.groupby(group_keys, as_index=False)[[year]].sum()

    # ------------------ Step 7 ------------------
    logger.info("[Step 7] Validate totals BEFORE pivot")
    total_before = df_region_wide[year].sum()
    # print(total_before, year )
    logger.info("[Step 7][%s] Total BEFORE = %.6f", year, total_before)

    by_carrier = df_region_wide.groupby(
        "pypsa_carrier", as_index=True
    )[year].sum()
    by_region = df_region_wide.groupby("Region", as_index=True)[year].sum()

    # ------------------ Step 8 ------------------
    logger.info("[Step 8] Reshape: one row per node, one column per carrier")
    sub = df_region_wide[["Region", "pypsa_carrier", year]].copy()
    wide = sub.pivot_table(
        index="Region",
        columns="pypsa_carrier",
        values=year,
        aggfunc="sum",
        fill_value=0.0,
    )
    # fix column names
    wide.columns = [canon(c) for c in wide.columns]        

    # --- 9A: totals right after pivot (all carriers) ---
    wide_all = _force_numeric(wide)  # ensure numeric before summing
    total_after_all = float(wide_all.to_numpy().sum())
    if abs(total_after_all - total_before) > 1e-9:
        logger.warning(
            "[Step 9][%s] Mismatch right after pivot (all carriers): Δ=%.6f (before=%.6f, after_all=%.6f)",
            year, total_after_all - total_before, total_before, total_after_all
        )
    else:
        logger.info("[Step 9][%s] Totals match right after pivot (all carriers).", year)

    # --- 9B: carriers that are NOT in TARGET_CARRIERS ---
    other_carriers = [c for c in wide_all.columns if c not in TARGET_CARRIERS]
    if other_carriers:
        other_sums = wide_all[other_carriers].sum().astype(float).sort_values(ascending=False)
        other_sum_total = float(other_sums.sum())
        logger.warning(
            "[Step 9][%s] Non-target carriers sum=%.6f. Top:\n%s",
            year, other_sum_total, other_sums.head(20).to_string(float_format=lambda v: f"{v:.6f}")
        )
    else:
        other_sum_total = 0.0
        logger.info("[Step 9][%s] No non-target carriers after pivot.", year)

    # --- now build the final table with only TARGET_CARRIERS (consistent output) ---
    # ensure missing target columns exist, then order them
    for c in ENERGY_CARRIERS:
        if c not in wide.columns:
            wide[c] = 0.0
    wide = wide.reindex(columns=ENERGY_CARRIERS, fill_value=0.0)

    # Add current_electricity
    wide["current electricity"] = df_today.reindex(wide.index).fillna(0.0)[current_electricity_year]

    # ------------------ Step 9 (final check on target-only) ------------------
    wide_num = _force_numeric(wide)
    total_after = float(wide_num.to_numpy().sum())
    delta = total_after - total_before
    if abs(delta) > 1e-9:
        logger.warning(
            "[Step 9][%s] Delta using TARGET_CARRIERS: %.6f (before=%.6f, after_target=%.6f)",
            year, delta, total_before, total_after
        )
    else:
        logger.info("[Step 9][%s] Totals match using TARGET_CARRIERS.", year)

    # Optional: fail hard in strict mode if there is material non-target energy
    if strict and other_carriers and other_sum_total > 1e-6:
        raise ValueError(
            f"[{year}] Non-target carrier energy {other_sum_total:.6f} exists in: "
            + ", ".join(list(map(str, other_carriers))[:10])
        )

    # Map to PyPSA-Eur regions
    logger.info("[Step 10] Map to PyPSA-Eur regions")
    gdf_industry = nuts3_shapes[["index", "geometry"]].copy()
    gdf_industry = gdf_industry.rename(columns={"index": "source_region"})
    
    # Merge data from wide to gdf
    gdf_industry = gdf_industry.merge(
        wide.reset_index(),
        left_on="source_region",
        right_on="Region",
        how="inner",
        validate="" \
        "1:1",
    )
    gdf_industry = gdf_industry.drop(columns=["Region"], errors="ignore")

    # Regions subset, only include regions that geographically covered by union of gdf_industry
    industry_union = gdf_industry.to_crs(3857).union_all()
    regions_m = regions.to_crs(3857)
    regions_m["area"] = regions_m.geometry.area
    regions_m["area_int"] = regions_m.geometry.intersection(industry_union).area
    regions_m["share"] = regions_m["area_int"] / regions_m["area"]
    regions_m = regions_m[regions_m["share"] > 0.99] # Ensure that bordering intersections to NL, BE, etc. are excluded
    regions_m = regions_m.drop(columns=["area", "area_int", "share"], errors="ignore")
    regions_m.reset_index(drop=True, inplace=True)

    mapped = proportional_overlay(
        source=gdf_industry,
        target=regions_m,
        source_id="source_region",
        target_id="name",
    )

    # Drop geometry, area, source_region columns
    mapped = mapped.drop(columns=["geometry", "source_region"], errors="ignore")

    #### PROCESS EMISSIONS ####
    # Process emissions, map using coordinates
    ipe_forecast["geometry"] = ipe_forecast.apply(
        lambda row: Point(row["longitude"], row["latitude"]),
        axis=1,
    )
    ipe_forecast = gpd.GeoDataFrame(
        ipe_forecast,
        crs="EPSG:4326"
    )
    ipe_forecast = ipe_forecast.to_crs("EPSG:3857")

    # Map using sjoin_nearest
    ipe_forecast = ipe_forecast.sjoin_nearest(
        regions_m.to_crs("EPSG:3857")[["name", "geometry"]],
        how="left",
        distance_col="dist_to_region",
    )

    # Sum by region and carrier for the selected year
    group_col = "name"
    ipe_wide = (
        ipe_forecast
        .dropna(subset=['pypsa_carrier'])          # keep only mapped carriers
        .groupby([group_col, 'pypsa_carrier'], as_index=False)[[year]]
        .sum()
        .pivot(index=group_col, columns='pypsa_carrier', values=year)
        .fillna(0.0)
    )

    # Reindex to mapped regions and add to mapped DataFrame
    ipe_wide = ipe_wide.reindex(mapped.index).fillna(0.0)
    
    logger.info("[Step 11] Add process emissions")
    for carrier in PROCESS_EMISSION_CARRIERS:
        if carrier in ipe_wide.columns:
            mapped[carrier] = ipe_wide[carrier]
        else:
            mapped[carrier] = 0.0
  
   #------------------ Step 11: Merge with original nodal industry ------------------      
    logger.info("[Step 11] Add process emissions")
    # Add process emissions to mapped
   
    # Merge with original nodal industry and only overwrite those from mapped
    industrial_energy_demand_per_node = pd.read_csv(snakemake.input.industrial_energy_demand_per_node)
    industrial_energy_demand_per_node.set_index(NODE_COL, inplace=True)

    # if oil not in columns, add it with zeros
    if "oil" not in industrial_energy_demand_per_node.columns:
        industrial_energy_demand_per_node["oil"] = 0.0
    
    forecast_industry = industrial_energy_demand_per_node.copy()
    forecast_industry.update(mapped)

    # Export
    logger.info("[Export %s] Wrote %s (rows=%d, cols=%d)")
    forecast_industry.sort_values(NODE_COL).to_csv(snakemake.output.industrial_energy_demand_per_node_forecast, index=True, float_format="%.4f")