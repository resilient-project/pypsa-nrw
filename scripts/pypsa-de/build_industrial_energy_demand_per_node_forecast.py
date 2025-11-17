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

from __future__ import annotations
from pathlib import Path
import logging, re
import pandas as pd

# Optional helper from your repo (for real Snakemake runs)

try:
    from scripts._helpers import configure_logging, mock_snakemake  # type: ignore
except Exception:
    configure_logging = None
    mock_snakemake = None

# ---------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Canonical column order in the final file
TARGET_CARRIERS = [
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
    "current electricity",
]
NODE_COL = "TWh/a (MtCO2/a)"
YEAR_MIN, YEAR_MAX = 1900, 2100

# ------------------ utilities functions ---------------------


def parse_years(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, str):
        raw = raw.strip()
        if "," in raw:  # 
            return [int(x) for x in raw.split(",") if x.strip()]
        return [int(raw)]
    if isinstance(raw, (list, tuple, set)):
        return [int(x) for x in raw]
    return [int(str(raw))]


def detect_year_columns(df: pd.DataFrame) -> list[str]:
    years = []
    for c in df.columns:
        s = str(c)
        if s.isdigit() and len(s) == 4:
            y = int(s)
            if YEAR_MIN <= y <= YEAR_MAX:
                years.append(s)
    return sorted(years, key=int)


def apply_rules_first_match(
    df: pd.DataFrame,
    rules: list[dict],
    *,
    energy_col: str = "Energy_carrier",  # only used for logs
    label_col: str = "pypsa_energy_carrier_mapping",
) -> pd.DataFrame:
    """
    Rule engine (first-match-wins):
      - rule = { pypsa_carrier: str, when: {col: [values...]}, unless: {col: [values...]}? }
      - 'when' keys are AND-combined; values in a key are OR-combined.
      - Column names are matched case-insensitively and treating spaces/underscores as equivalent.
      - 'unless' excludes rows if ANY of its conditions matches.
    """
    out = df.copy()
    out[label_col] = pd.NA

    # lookup that tolerates space/underscore + case
    cols = list(out.columns)
    norm = lambda s: str(s).strip().lower().replace(" ", "_")
    col_lookup = {norm(c): c for c in cols}

    def resolve_col(key: str) -> str | None:
        # try as-is, then normalized, then flip space/underscore
        if key in out.columns:
            return key
        k = norm(key)
        if k in col_lookup:
            return col_lookup[k]
        flip = key.replace(" ", "_") if " " in key else key.replace("_", " ")
        k2 = norm(flip)
        if k2 in col_lookup:
            return col_lookup[k2]
        return None

    def mask_when(frame: pd.DataFrame, cond: dict | None) -> pd.Series:
        if not cond:
            return pd.Series(True, index=frame.index)
        m = pd.Series(True, index=frame.index)
        for raw_col, vals in cond.items():
            col = resolve_col(raw_col)
            if col is None:
                logger.debug("[Rules] 'when' key '%s' not found in data columns; this rule won't match on that key.", raw_col)
                return pd.Series(False, index=frame.index)  # missing 'when' key => fail
            vals = set(vals or [])
            m = m & frame[col].isin(vals)
        return m

    def mask_unless(frame: pd.DataFrame, cond: dict | None) -> pd.Series:
        if not cond:
            return pd.Series(False, index=frame.index)  # nothing to exclude
        m_any = pd.Series(False, index=frame.index)
        for raw_col, vals in cond.items():
            col = resolve_col(raw_col)
            if col is None:
                logger.debug("[Rules] 'unless' key '%s' not found in data; ignoring that key.", raw_col)
                continue
            vals = set(vals or [])
            m_any = m_any | frame[col].isin(vals)
        return m_any  # True means exclude
    # --------------------------------------------------------

    logger.info("[Step 3] Applying %d carrier rules (first-match-wins)...", len(rules))
    total = len(out)
    for i, rule in enumerate(rules, start=1):
        carrier = rule.get("pypsa_carrier")
        when = rule.get("when", {}) or {}
        unless = rule.get("unless", {}) or {}

        base = out[label_col].isna()
        m_when = mask_when(out, when)
        m_unless = mask_unless(out, unless)
        mask = base & m_when & (~m_unless)

        n = int(mask.sum())
        if n:
            out.loc[mask, label_col] = carrier
            logger.debug("[Rule %02d] -> '%s' on %d rows", i, carrier, n)
        else:
            logger.debug("[Rule %02d] no matches", i)

        labeled = int(out[label_col].notna().sum())
    total = len(out)
    logger.info("[Step 3] Labeled %d/%d rows (%.1f%%).", labeled, total, 100 * labeled / max(total, 1))

    # ----  unmatched summaries ----
    unmatched = out[out[label_col].isna()]
    n_unmatched = len(unmatched)
    if n_unmatched:
        logger.warning("[Step 3] Unmatched rows: %d.", n_unmatched)

        # By energy carrier (top 20)
        if "Energy_carrier" in unmatched.columns:
            vc_car = unmatched["Energy_carrier"].value_counts().head(20)
            logger.info("[Step 3] Unmatched by Energy_carrier (top 20):\n%s", vc_car.to_string())

        # By (Energy_carrier, Application) pairs (top 20)
        cols_pair = [c for c in ["Energy_carrier", "Application"] if c in unmatched.columns]
        if len(cols_pair) == 2:
            by_pair = (unmatched.groupby(cols_pair).size()
                                  .sort_values(ascending=False)
                                  .head(20))
            logger.info("[Step 3] Unmatched by (Energy_carrier, Application) (top 20):\n%s",
                        by_pair.to_string())

        # By Subsector (top 20)
        if "Subsector" in unmatched.columns:
            vc_sub = unmatched["Subsector"].value_counts().head(20)
            logger.info("[Step 3] Unmatched by Subsector (top 20):\n%s", vc_sub.to_string())

        # Optional: quick glance at example rows (first 10)
        show_cols = [c for c in ["Country","Region","Subsector","Application","Energy_carrier"] if c in unmatched.columns]
        if show_cols:
            head = unmatched[show_cols].head(10)
            logger.info("[Step 3] Unmatched example rows (first 10):\n%s", head.to_string(index=False))
    else:
        logger.info("[Step 3] Great — no unmatched rows.")

    return out

def build_output_path_for_year(base_path: Path, year: int) -> Path:
    """
    Multi-year export naming without extra dirs:
    1) If '{year}' in name: replace it.
    2) If a bracketed list of years like '[2030, 2040]' appears, replace that whole list with the current year.
    3) Else replace the last 4-digit year in the stem.
    4) Else append _{year} before the suffix.
    """
    name = base_path.name
    y = str(year)

    # 1) Explicit placeholder
    if "{year}" in name:
        return base_path.with_name(name.replace("{year}", y))

    # 2) Replace any bracketed list of years (e.g., [2030, 2040] or [2030,2040])
    #    Pattern: [ <year>(, <year>)+ ] with optional spaces
    name2 = re.sub(r"\[\s*\d{4}(?:\s*,\s*\d{4})+\s*\]", y, name)
    if name2 != name:
        return base_path.with_name(name2)

    # 3) Replace the last 4-digit year in the stem (handles names that already have a single year)
    stem, suffix = base_path.stem, base_path.suffix
    matches = list(re.finditer(r"(19|20)\d{2}", stem))
    if matches:
        s, e = matches[-1].span()
        new_stem = stem[:s] + y + stem[e:]
        return base_path.with_name(new_stem + suffix)

    # 4) Fallback: append _{year}
    return base_path.with_name(f"{stem}_{y}{suffix}")
  
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

# ----------------------- main -------------------------------

if __name__ == "__main__":
    # Snakemake / local testing bootstrap
    if "snakemake" not in globals():
        if mock_snakemake is None:
            raise RuntimeError(
                "This script is Snakemake-only. Run via Snakemake or provide mock_snakemake in scripts/_helpers."
            )
        snakemake = mock_snakemake(
            "build_industrial_energy_demand_per_node_modified_forecast",
            run="baseline",
            clusters=48,
            planning_horizons=[2030, 2040, 2050],
            industry_scenario="Orientierungsszenario_Strom",
            configfiles=["config/config.nrw.yaml"],
        )
        
    
    if not logger.handlers:
      logging.basicConfig(
          level=logging.INFO,  
          format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
      )
    logger.setLevel(logging.DEBUG)  
    logger.info("[Debug] Effective log level = %s", logging.getLevelName(logger.getEffectiveLevel()))

    # ------------------ Step 1: Load ------------------
    logger.info("[Step 1] Load inputs")
    df_forecast = pd.read_csv(snakemake.input.industry_sector_forecast_fed, index_col=0)
    df_region_map = pd.read_csv(snakemake.input.forecast_to_pypsa_mapping, index_col=0)
    rules = (snakemake.config.get("forecast_industry", {}) or {}).get(
        "forecast_pypsa_mapping_rules", []
    )
    if not rules:
        raise ValueError(
            "Missing config.forecast_industry.forecast_pypsa_mapping_rules."
        )
    strict = bool(
        (getattr(snakemake, "params", {}) or {}).get(
            "strict_industry_validation", False
        )
    )

    # ------------------ Step 2: planning_horizons & years ------------------
    logger.info("[Step 2] Parse planning_horizons & detect years")
    raw_ph = getattr(snakemake.wildcards, "planning_horizons")
    years = parse_years(raw_ph)
    if not years:
        raise ValueError("planning_horizons is missing or empty.")

    year_cols = detect_year_columns(df_forecast)
    if not year_cols:
        raise ValueError("No 4-digit year columns found in FORECAST table.")
    missing = [str(y) for y in years if str(y) not in year_cols]
    if missing:
        avail = f"{year_cols[:10]}{'...' if len(year_cols) > 10 else ''}"
        raise ValueError(
            f"Requested planning_horizons not in data: {missing}. Available: {avail}"
        )

    multi_year = len(years) > 1

    # ------------------ Step 3: keep year columns (single vs multi) ------------------
    if not multi_year:
        year = years[0]
        drop_year_cols = [c for c in year_cols if c != str(year)]
        df_forecast = df_forecast.drop(columns=drop_year_cols, errors="ignore")
        logger.info(
            "[Step 3] Keeping year column %s; dropped %s",
            str(year),
            drop_year_cols or "none",
        )
    else:
        logger.info(
            "[Step 3] Multi-year run detected (%s). Keeping all year columns; per-year slicing inside the loop.",
            ", ".join(map(str, years)),
        )

    # ------------------ Step 4: Apply carrier / region mapping ------------------
    df_map_car = apply_rules_first_match(
        df_forecast, rules, energy_col="Energy_carrier"
    )

    logger.info("[Step 4] Map regions forecast_region → pypsa_region")
    df_mapped = df_map_car.merge(
        df_region_map,
        left_on="Region",
        right_on="forecast_region",
        how="left",
        validate="m:m",
    )
    n_unmapped = int(df_mapped["pypsa_region"].isna().sum())
    if n_unmapped:
        logger.warning("[Step 4] Unmapped forecast regions: %d", n_unmapped)
        if strict:
            top = (
                df_mapped[df_mapped["pypsa_region"].isna()]
                .groupby("Region")
                .size()
                .sort_values(ascending=False)
                .head(12)
            )
            logger.debug("[Step 4] Unmapped regions (top):\n%s", top.to_string())

    # ------------------ Export setup (reuse single-year path pattern) ------------------
    base_fn = Path(snakemake.output.industrial_energy_demand_per_node)
    base_fn.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[Export] output path: %s", base_fn)

    for year in years:
        ycol = str(year)
        logger.info("========== Year %s ==========", ycol)

        # ------------------ Step 5 ------------------
        logger.info("[Step 5] Prune to essential columns (%s)", ycol)
        keep = [
            "Country",
            "Subsector",
            "Application",
            "Energy_carrier",
            "pypsa_region",
            "pypsa_energy_carrier_mapping",
            ycol,
        ]
        keep = [c for c in keep if c in df_mapped.columns]
        if ycol not in keep:
            logger.error("[Year %s] Column not found in data; skipping.", ycol)
            continue
        df_pruned = df_mapped[keep].copy()
        df_pruned["pypsa_energy_carrier_mapping"] = df_pruned["pypsa_energy_carrier_mapping"].map(canon)

        # ------------------ Step 6 ------------------
        logger.info("[Step 6] Aggregate to pypsa_region (wide by year %s)", ycol)
        group_keys = [
            k
            for k in [
                "Country",
                "pypsa_region",
                "pypsa_energy_carrier_mapping",
                "Subsector",
                "Application",
            ]
            if k in df_pruned.columns
        ]
        df_region_wide = df_pruned.groupby(group_keys, as_index=False)[[ycol]].sum()

        # ------------------ Step 7 ------------------
        logger.info("[Step 7] Validate totals BEFORE pivot")
        total_before = df_region_wide[ycol].sum()
        # print(total_before, ycol )
        logger.info("[Step 7][%s] Total BEFORE = %.6f", ycol, total_before)

        by_carrier = df_region_wide.groupby(
            "pypsa_energy_carrier_mapping", as_index=True
        )[ycol].sum()
        by_region = df_region_wide.groupby("pypsa_region", as_index=True)[ycol].sum()

      # ------------------ Step 8 ------------------
        logger.info("[Step 8] Reshape: one row per node, one column per carrier")
        sub = df_region_wide[["pypsa_region", "pypsa_energy_carrier_mapping", ycol]].copy()
        wide = sub.pivot_table(
            index="pypsa_region",
            columns="pypsa_energy_carrier_mapping",
            values=ycol,
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
                ycol, total_after_all - total_before, total_before, total_after_all
            )
        else:
            logger.info("[Step 9][%s] Totals match right after pivot (all carriers).", ycol)

        # --- 9B: carriers that are NOT in TARGET_CARRIERS ---
        other_carriers = [c for c in wide_all.columns if c not in TARGET_CARRIERS]
        if other_carriers:
            other_sums = wide_all[other_carriers].sum().astype(float).sort_values(ascending=False)
            other_sum_total = float(other_sums.sum())
            logger.warning(
                "[Step 9][%s] Non-target carriers sum=%.6f. Top:\n%s",
                ycol, other_sum_total, other_sums.head(20).to_string(float_format=lambda v: f"{v:.6f}")
            )
        else:
            other_sum_total = 0.0
            logger.info("[Step 9][%s] No non-target carriers after pivot.", ycol)

        # --- now build the final table with only TARGET_CARRIERS (consistent output) ---
        # ensure missing target columns exist, then order them
        for c in TARGET_CARRIERS:
            if c not in wide.columns:
                wide[c] = 0.0
        wide = wide.reindex(columns=TARGET_CARRIERS, fill_value=0.0)

        # ------------------ Step 9 (final check on target-only) ------------------
        wide_num = _force_numeric(wide)
        total_after = float(wide_num.to_numpy().sum())
        delta = total_after - total_before
        if abs(delta) > 1e-9:
            logger.warning(
                "[Step 9][%s] Delta using TARGET_CARRIERS: %.6f (before=%.6f, after_target=%.6f)",
                ycol, delta, total_before, total_after
            )
        else:
            logger.info("[Step 9][%s] Totals match using TARGET_CARRIERS.", ycol)

        # Optional: fail hard in strict mode if there is material non-target energy
        if strict and other_carriers and other_sum_total > 1e-6:
            raise ValueError(
                f"[{ycol}] Non-target carrier energy {other_sum_total:.6f} exists in: "
                + ", ".join(list(map(str, other_carriers))[:10])
            )

        # finalize shape and export
        wide = wide.reset_index().rename(columns={"pypsa_region": NODE_COL})

        # ------------------ Step 10 ------------------
        fn = build_output_path_for_year(base_fn, year) if len(years) > 1 else base_fn
        wide.sort_values(NODE_COL).reset_index(drop=True).to_csv(fn, index=False, float_format="%.2f")
        logger.info("[Export %s] Wrote %s (rows=%d, cols=%d)", ycol, fn, *wide.shape)