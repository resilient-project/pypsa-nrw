#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from __future__ import annotations

import logging
import geopandas as gpd
from pathlib import Path
import re

import pandas as pd

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)

# Regex for NUTS codes:
# - NUTS0: 2 letters (e.g., "DE")
# - NUTS1: 3 chars (letters/digits), e.g., "DE1"
# - NUTS2: 4 chars, e.g., "DE12"
# - NUTS3: 5 chars, e.g., "DE123"
# We allow upper/lower case just in case. No fuzzy matching.
NUTS_CODE_PATTERN = re.compile(r"[A-Za-z]{2}[A-Za-z0-9]{0,3}")


def extract_nuts_codes(x) -> list[str]:
    """
    Extract valid NUTS codes from a string (separated by '+' or ','),
    a list of strings, or a pandas Series element.

    Returns an order-preserving list of uppercase codes that fully match NUTS regex.
    """
    if x is None:
        return []

    # Normalize to list[str]
    if isinstance(x, str):
        # split on '+' or ','; strip whitespace
        parts = re.split(r"[+,]", x)
        tokens = [p.strip() for p in parts if p and p.strip()]
    elif isinstance(x, (list, tuple)):
        tokens = [
            str(t).strip() for t in x if isinstance(t, (str, int)) and str(t).strip()
        ]
    else:
        # e.g., numbers/NaN/other types → nothing
        return []

    # Validate with fullmatch and normalize to uppercase
    out = []
    seen = set()
    for t in tokens:
        if NUTS_CODE_PATTERN.fullmatch(t):
            u = t.upper()
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def nuts0_from_codes(codes: set[str]) -> set[str]:
    """
    Compute the set of NUTS-0 (country) codes from a set of NUTS codes.

    NUTS-0 is the first two characters of any valid NUTS code.

    Parameters
    ----------
    codes : set[str]
        Set of NUTS codes at any level (0–3).

    Returns
    -------
    set[str]
        Set of NUTS-0 country codes (two letters), e.g., {'DE','FR'}.
    """
    return {c[:2].upper() for c in codes if isinstance(c, str) and len(c) >= 2}


def get_nuts_level_name(code: str) -> str:
    """
    Return NUTS level name (NUTS0..NUTS3) based on code length.
    2 -> NUTS0, 3 -> NUTS1, 4 -> NUTS2, 5 -> NUTS3. Anything else -> 'LEN{n}'.
    """
    if not isinstance(code, str):
        return "LEN0"
    L = len(code)
    return {2: "NUTS0", 3: "NUTS1", 4: "NUTS2", 5: "NUTS3"}.get(L, f"LEN{L}")


def generate_ancestors(code: str) -> list[str]:
    """
    Produce truncated ancestors by length, longest to shortest, excluding the original code.
    Example: 'DEA15' -> ['DEA1','DEA','DE'].
    We only truncate to lengths 4, 3, 2 (NUTS2, NUTS1, NUTS0).
    """
    if not isinstance(code, str):
        return []
    code = code.strip()
    L = len(code)
    targets = [4, 3, 2]
    return [code[:k] for k in targets if L > k]


def _normalize_for_union(df, default_agg=False) -> pd.DataFrame:
    """Ensure all mapping DataFrames share the same columns for concatenation."""
    cols = [
        "forecast_region",
        "forecast_level",
        "pypsa_region",
        "pypsa_region_level",
        "match_kind",
        "aggregate_upward",
        "aggregate_from_code",
        "aggregate_to_code",
    ]
    if df is None or len(df) == 0:
        out = pd.DataFrame(columns=cols)
        return out
    out = df.copy()
    if "aggregate_upward" not in out.columns:
        out["aggregate_upward"] = default_agg
    for c in ("aggregate_from_code", "aggregate_to_code"):
        if c not in out.columns:
            out[c] = pd.NA
    return out[cols]


if __name__ == "__main__":
    # --- Snakemake / local testing bootstrap ---
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_industrial_regions_map_forecast_to_pypsa",    
            industry_scenario="Orientierungsszenario_H2",
            run="KN2045_Mix",
            configfiles=["config/config.nrw.yaml"],
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    
    # ===== Step 1: Load and validate datasets ---
    # --- Load data ---
    fn = snakemake.input.industry_sector_forecast_fed
    forecast_df = pd.read_csv(fn, index_col=0)
    admin_shapes = gpd.read_file(snakemake.input.admin_shapes)

    # --- Step 2: Validate and extract unique regions ---
    # validate and extract unique regions from both datasets ---
    # Validate required column in Forecast dataset exists
    if "Region" not in forecast_df.columns:
        raise ValueError(
            "[Required column 'Region' not found. "
            f"Columns seen: {forecast_df.columns.tolist()[:20]}"
        )

    # extract unique region names as a Series
    # FORECAST regions
    df_forecast_regions = (
        forecast_df["Region"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .to_frame(name="forecast_region")
    )

    logger.info(
        "[Step 1] Loaded data [forecast] for scenario '%s' unique regions: %d",
        snakemake.wildcards.industry_scenario,
        len(df_forecast_regions),
    )

    # PyPSA regions
    required_cols = {"admin", "contains"}
    missing = required_cols - set(admin_shapes.columns)
    if missing:
        raise ValueError(
            f"[pypsa] admin_shapes missing required columns: {sorted(missing)}"
        )
    nuts_codes_pypsa = admin_shapes["admin"].drop_duplicates().reset_index(drop=True)
    logger.info(
        "[Step 1] Loaded data [pypsa] admin shapes, unique regions: %d",
        len(nuts_codes_pypsa),
    )

    # ===== Step 3: identify regions in PyPSA that are aggregate more than one NUTS region  ---
    # Split PyPSA admin names by '+' and extract NUTS codes
    # Build PyPSA regions catalog and members link table
    pypsa_regions_rows = (
        []
    )  # PyPSA region labels it might aggregate multiple NUTS regions if no substations exist could be identified by '+' in the admin
    pypsa_members_rows = (
        []
    )  # PyPSA regions including the aggregated nuts regions within on level, identified by the + in the admin
    for _, row in admin_shapes[["admin", "contains"]].iterrows():
        # A PyPSA "region" is the model node label stored in 'admin'
        pypsa_region = str(row["admin"]) if row["admin"] is not None else ""
        # Members are the list of NUTS codes that this region contains (parsed from 'contains')
        member_list = extract_nuts_codes(row["contains"])

        is_aggregated = (len(member_list) > 1) or ("+" in pypsa_region)
        n_members = len(member_list)

        # Assign a NUTS level (NUTS0–NUTS3):
        # - If all members (regions) share the same NUTS level, use that
        # - If no members but region looks like a NUTS code, use its length-based level
        # - Otherwise mark as "mixed" or "unknown"
        if n_members >= 1:
            levels = {get_nuts_level_name(m) for m in member_list}
            pypsa_region_level = levels.pop() if len(levels) == 1 else "mixed"
        else:
            pypsa_region_level = (
                get_nuts_level_name(pypsa_region)
                if NUTS_CODE_PATTERN.fullmatch(pypsa_region or "")
                else "unknown"
            )

        pypsa_regions_rows.append(
            {
                "pypsa_region": pypsa_region,
                "pypsa_region_level": pypsa_region_level,
                "is_aggregated": bool(is_aggregated),
                "n_members": int(n_members),
            }
        )

        for m in member_list:
            pypsa_members_rows.append(
                {
                    "pypsa_region": pypsa_region,
                    "pypsa_member_code": m,
                    "pypsa_member_level": get_nuts_level_name(m),
                }
            )

    df_pypsa_regions_catalog = pd.DataFrame(pypsa_regions_rows)
    df_pypsa_region_members = pd.DataFrame(pypsa_members_rows)

    # --------------------- Logging: summaries -------------------
    n_regions = len(df_pypsa_regions_catalog)
    n_regions_unique = df_pypsa_regions_catalog["pypsa_region"].nunique()
    n_members_links = len(df_pypsa_region_members)

    n_singletons = int((~df_pypsa_regions_catalog["is_aggregated"]).sum())
    n_aggregated = int(df_pypsa_regions_catalog["is_aggregated"].sum())
    avg_members_aggregated = (
        df_pypsa_regions_catalog.loc[
            df_pypsa_regions_catalog["is_aggregated"], "n_members"
        ].mean()
        if n_aggregated > 0
        else 0.0
    )

    logger.info(
        "[Step 3] data analysis [pypsa] regions catalog: %d rows (unique regions=%d)",
        n_regions,
        n_regions_unique,
    )
    logger.info(
        "[Step 3] data analysis [pypsa] regions include: %d singleton and  %d aggregated (avg members per aggregated region=%.2f)",
        n_singletons,
        n_aggregated,
        avg_members_aggregated,
    )

    logger.info(
        "[Step 3] data analysis [pypsa] member links (region→member) including aggregated (within the same NUTS level due to the absence of substations): %d",
        n_members_links,
    )

    # Show a few examples of each type for quick sanity
    if n_aggregated > 0:
        example_agg = (
            df_pypsa_regions_catalog[df_pypsa_regions_catalog["is_aggregated"]]
            .sort_values("n_members", ascending=False)
            .head(3)["pypsa_region"]
            .tolist()
        )
        logger.info(
            "[Step 3] data analysis [pypsa] example aggregated regions: %s", example_agg
        )

    if n_singletons > 0:
        example_single = (
            df_pypsa_regions_catalog[~df_pypsa_regions_catalog["is_aggregated"]]
            .head(3)["pypsa_region"]
            .tolist()
        )
        logger.info(
            "[Step 3] data analysis [pypsa] example singleton regions: %s",
            example_single,
        )

    # ===== step 4: Forecast catalog
    # Build FORECAST regions catalog
    df_forecast_regions["forecast_level"] = df_forecast_regions["forecast_region"].map(
        get_nuts_level_name
    )

    logger.info("[Step 4] [forecast] unique regions: %d", len(df_forecast_regions))

    nuts0_forecast: set[str] = nuts0_from_codes(
        df_forecast_regions["forecast_region"].unique()
    )
    logger.info(
        "[Step 4] [forecast] data contains %d countries %s:",
        len(nuts0_forecast),
        sorted(nuts0_forecast),
    )

    # PyPSA NUTS codes from admin_shapes.geojson
    nuts0_pypsa: set[str] = nuts0_from_codes(nuts_codes_pypsa)
    logger.info(
        "[Step 4] [pypsa] data contains %d countries %s:",
        len(nuts0_pypsa),
        sorted(nuts0_pypsa),
    )
    # --- Step 2: Identify missing NUTS-0 countries ---
    # Compare NUTS-0 countries in both datasets
    # PyPSA expects these NUTS-0 but FORECAST doesn't have them
    nuts0_missing_in_forecast = sorted(nuts0_pypsa - nuts0_forecast)
    logger.info(
        "[Step 4] [forecast] %d Countries Missing in FORECAST (present only in PyPSA) %s:",
        len(nuts0_missing_in_forecast),
        sorted(nuts0_missing_in_forecast),
    )
    # FORECAST includes these NUTS-0 that PyPSA doesn't reference
    nuts0_missing_in_pypsa = sorted(nuts0_forecast - nuts0_pypsa)
    logger.info(
        "[Step 4] [forecast-pypsa] %d Countries Missing in PyPSA (present only in FORECAST) %s:",
        len(nuts0_missing_in_pypsa),
        sorted(nuts0_missing_in_pypsa),
    )

    # ===== Step 5: Direct one-to-one matches (singleton PyPSA regions) ============
    # Definition of a singleton here:
    #   - PyPSA region is not flagged as aggregated
    #   - And region label does not contain '+'
    df_pypsa_singleton_regions = df_pypsa_regions_catalog[
        (~df_pypsa_regions_catalog["is_aggregated"])
        & (~df_pypsa_regions_catalog["pypsa_region"].astype(str).str.contains(r"\+"))
    ].copy()

    df_step5_direct_singleton = df_forecast_regions.merge(
        df_pypsa_singleton_regions[["pypsa_region", "pypsa_region_level"]],
        left_on="forecast_region",
        right_on="pypsa_region",
        how="inner",
    ).assign(match_kind="direct")

    logger.info(
        "[Step 5] Direct singleton matches: %d (of %d forecast regions).",
        len(df_step5_direct_singleton),
        len(df_forecast_regions),
    )

    # ===== Step 6: Matches via aggregated PyPSA regions (members in 'contains') ===
    # Work only on FORECAST regions not matched in Step 5
    matched_step5 = (
        set(df_step5_direct_singleton["forecast_region"])
        if len(df_step5_direct_singleton)
        else set()
    )
    df_forecast_pool_step6 = df_forecast_regions[
        ~df_forecast_regions["forecast_region"].isin(matched_step5)
    ].copy()

    # Identify aggregated PyPSA regions (either flagged or '+' in label)
    pypsa_aggregated = df_pypsa_regions_catalog[
        (df_pypsa_regions_catalog["is_aggregated"])
        | (df_pypsa_regions_catalog["pypsa_region"].astype(str).str.contains(r"\+"))
    ]["pypsa_region"]

    df_members_aggregated = df_pypsa_region_members[
        df_pypsa_region_members["pypsa_region"].isin(pypsa_aggregated)
    ].copy()

    # Join: FORECAST region equals a PyPSA member code
    df_step6_raw = df_forecast_pool_step6.merge(
        df_members_aggregated,
        left_on="forecast_region",
        right_on="pypsa_member_code",
        how="inner",
    )

    # Attach PyPSA region metadata (level)
    df_step6_member_of_aggregated = df_step6_raw.merge(
        df_pypsa_regions_catalog[["pypsa_region", "pypsa_region_level"]],
        on="pypsa_region",
        how="left",
    )

    # Classify the relationship:
    # - within_level: forecast_level == pypsa_member_level
    # - aggregate_up: forecast_level is finer than pypsa_member_level
    def _classify_step6(row) -> str:
        return (
            "within_level"
            if row["forecast_level"] == row["pypsa_member_level"]
            else "aggregate_up"
        )

    df_step6_member_of_aggregated["match_kind"] = df_step6_member_of_aggregated.apply(
        _classify_step6, axis=1
    )

    logger.info(
        "[Step 6] Matches via aggregated PyPSA regions: %d (within-level=%d, aggregate-up=%d)",
        len(df_step6_member_of_aggregated),
        int((df_step6_member_of_aggregated["match_kind"] == "within_level").sum()),
        int((df_step6_member_of_aggregated["match_kind"] == "aggregate_up").sum()),
    )

    # ===== Step 7: Aggregate-up fallback via NUTS ancestors =======================
    # Remaining pool after Steps 5 and 6
    matched_step6 = (
        set(df_step6_member_of_aggregated["forecast_region"])
        if len(df_step6_member_of_aggregated)
        else set()
    )
    df_forecast_pool_step7 = df_forecast_regions[
        ~df_forecast_regions["forecast_region"].isin(matched_step5 | matched_step6)
    ].copy()

    # Fast lookups
    member_to_pypsa = dict(
        zip(
            df_pypsa_region_members["pypsa_member_code"],
            df_pypsa_region_members["pypsa_region"],
        )
    )

    singleton_pypsa_regions = set(
        df_pypsa_regions_catalog.loc[
            (~df_pypsa_regions_catalog["is_aggregated"])
            & (
                ~df_pypsa_regions_catalog["pypsa_region"]
                .astype(str)
                .str.contains(r"\+")
            )
        ]["pypsa_region"]
    )

    rows_step7 = []
    for _, r in df_forecast_pool_step7.iterrows():
        f_code = r["forecast_region"]
        f_level = r["forecast_level"]
        chosen_pypsa = None
        chosen_pypsa_level = None
        chosen_kind = None
        used_ancestor = None

        # Try ancestors in order: NUTS2 -> NUTS1 -> NUTS0
        for anc in generate_ancestors(f_code):
            # If ancestor is a PyPSA member, map to that region (aggregate_up)
            if anc in member_to_pypsa:
                chosen_pypsa = member_to_pypsa[anc]
                chosen_pypsa_level = get_nuts_level_name(anc)
                chosen_kind = "aggregate_up"
                used_ancestor = anc
                break
            # If ancestor is a singleton PyPSA region, map directly
            if anc in singleton_pypsa_regions:
                chosen_pypsa = anc
                chosen_pypsa_level = get_nuts_level_name(anc)
                chosen_kind = "direct"
                used_ancestor = anc
                break

        if chosen_pypsa is not None:
            rows_step7.append(
                {
                    "forecast_region": f_code,
                    "forecast_level": f_level,
                    "pypsa_region": chosen_pypsa,
                    "pypsa_region_level": chosen_pypsa_level,
                    "match_kind": chosen_kind,
                    "aggregate_upward": True,
                    "aggregate_from_code": f_code,
                    "aggregate_to_code": used_ancestor,
                }
            )

    df_step7_aggregate_up_ancestors = pd.DataFrame(
        rows_step7,
        columns=[
            "forecast_region",
            "forecast_level",
            "pypsa_region",
            "pypsa_region_level",
            "match_kind",
            "aggregate_upward",
            "aggregate_from_code",
            "aggregate_to_code",
        ],
    )

    logger.info(
        "[Step 7] Aggregate-up via ancestors: %d", len(df_step7_aggregate_up_ancestors)
    )

    # ===== Step 8: Final mapping + unmatched diagnostics ==========================

    df5 = _normalize_for_union(df_step5_direct_singleton, default_agg=False)
    df6 = _normalize_for_union(df_step6_member_of_aggregated, default_agg=False)
    df7 = _normalize_for_union(df_step7_aggregate_up_ancestors, default_agg=True)

    # Priority order: Step 5 (direct) > Step 6 (aggregated members) > Step 7 (aggregate-up)
    df_union = pd.concat([df5, df6, df7], ignore_index=True)
    df_union["__order"] = range(len(df_union))

    df_mapping_final = (
        df_union.sort_values(["forecast_region", "__order"])
        .drop_duplicates(subset=["forecast_region"], keep="first")
        .drop(columns="__order")
        .reset_index(drop=True)
    )

    logger.info(
        "[Step 8] Final mapping: %d of %d forecast regions matched.",
        len(df_mapping_final),
        len(df_forecast_regions),
    )

    # Unmatched FORECAST regions (your requested term; no 'zero demand' phrasing)
    df_unmatched_forecast = (
        df_forecast_regions.merge(
            df_mapping_final[["forecast_region"]],
            on="forecast_region",
            how="left",
            indicator=True,
        )
        .query("_merge == 'left_only'")
        .drop(columns="_merge")
        .reset_index(drop=True)
    )

    logger.info("[Step 8] Unmatched FORECAST regions: %d", len(df_unmatched_forecast))

    # Unmatched PyPSA regions = PyPSA regions that received no mapping
    df_unmatched_pypsa_regions = (
        df_pypsa_regions_catalog[["pypsa_region", "pypsa_region_level"]]
        .merge(
            df_mapping_final[["pypsa_region"]].drop_duplicates(),
            on="pypsa_region",
            how="left",
            indicator=True,
        )
        .query("_merge == 'left_only'")
        .drop(columns="_merge")
        .reset_index(drop=True)
    )

    logger.info("[Step 8] Unmatched PyPSA regions: %d", len(df_unmatched_pypsa_regions))  
    # ===== Step 9: Save outputs ================================================
    # Save final mapping to CSV
    # ===== Step 9: Save results to Snakemake outputs =============================
    logger.info("[Step 9] Saving mapping results to Snakemake outputs...")

    # save main outputs
    df_mapping_final.to_csv(snakemake.output.forecast_to_pypsa_mapping, index=False)
    df_unmatched_forecast.to_csv(snakemake.output.unmatched_forecast, index=False)
    df_unmatched_pypsa_regions.to_csv(snakemake.output.unmatched_pypsa, index=False)

    logger.info("[Step 9]  saving forecast_to_pypsa_mapping → %s (%d rows)", snakemake.output.forecast_to_pypsa_mapping, len(df_mapping_final))
    logger.info("[Step 9]  saving unmatched_forecast → %s (%d rows)", snakemake.output.unmatched_forecast, len(df_unmatched_forecast))
    logger.info("[Step 9]  saving unmatched_pypsa → %s (%d rows)", snakemake.output.unmatched_pypsa, len(df_unmatched_pypsa_regions))

    
