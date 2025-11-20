# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Create interactive maps for the defined carriers.
"""

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import geopandas as gpd
import pypsa
import pydeck as pdk

from pypsa.plot.maps.interactive import PydeckPlotter
from pypsa.statistics import get_transmission_carriers

from scripts._helpers import (
    PYPSA_V1,
    configure_logging,
    set_scenario_config,
    update_config_from_wildcards,
)

from scripts.add_electricity import sanitize_carriers

VALID_MAP_STYLES = PydeckPlotter.VALID_MAP_STYLES


def price_to_color(
    price, 
    cmap,
    vmin,
    vmax,    
    alpha=1):

    cmap = cmap or "Reds"    

    ccmap = plt.get_cmap(cmap) 
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    color = ccmap(norm(price))  # RGBA in 0-1
    rgb = [round(c * 255) for c in color[:3]]  # only RGB
    a = round(alpha * 255)
    return rgb + [a]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "plot_interactive_map",
            clusters="adm",
            opts="",
            sector_opts="",
            planning_horizons="2035",
            carrier="co2_stored",
            configfiles=["config/config.nrw-workshop.yaml"],
            run="forecast-co2-pipelines-min-ccs",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # Interactive map settings
    settings = snakemake.params.settings
    conversion = settings.get("conversion") or 1
    region_cmap = settings.get("region_cmap") or "Reds"
    region_alpha = settings.get("region_alpha") or 0.7
    region_unit = settings.get("region_unit") or ""
    branch_color = settings.get("branch_color") or "orange"
    arrow_size_factor = settings.get("arrow_size_factor") or 1.5 # PyPSA default
    bus_size_max = settings.get("bus_size_max") or 10000  # PyPSA default
    branch_width_max = settings.get("branch_width_max") or 10 # PyPSA default
    map_style = (
        str(settings.get("map_style")) or "road"
    ).lower()
    map_style = VALID_MAP_STYLES.get(map_style, "road")
    tooltip = settings.get("tooltip") or True

    # Import
    n = pypsa.Network(snakemake.input.network)
    sanitize_carriers(n, snakemake.config)
    pypsa.options.params.statistics.round = 6
    pypsa.options.params.statistics.drop_zero = True
    pypsa.options.params.statistics.nice_names = False

    regions = gpd.read_file(snakemake.input.regions).set_index("name")
    carrier = snakemake.wildcards.carrier
    carrier = carrier.replace("_", " ")

    # Fill missing carrier colors
    missing_color = "#808080"
    b_missing = n.carriers.query("color == '' or color.isnull()").index
    n.carriers.loc[b_missing, "color"] = missing_color

    transmission_carriers = get_transmission_carriers(
        n,
        bus_carrier=carrier
    ).rename({"name": "carrier"})
    components = transmission_carriers.unique("component")
    carriers = transmission_carriers.unique("carrier")

    ### Pie charts
    eb = n.statistics.energy_balance(
        bus_carrier=carrier,
        groupby=["bus", "carrier"],
    )

    # Only carriers that are also in the energy balance
    carriers_in_eb = carriers[carriers.isin(eb.index.get_level_values("carrier"))]

    eb.loc[components] = eb.loc[components].drop(
        index=carriers_in_eb,
        level="carrier"
    )
    eb = eb.dropna()
    bus_size = eb.groupby(level=["bus", "carrier"]).sum()

    # line and links widths according to optimal capacity
    flow = n.statistics.transmission(groupby=False, bus_carrier=carrier)
    if not flow.empty:
        flow_reversed_mask = flow.index.get_level_values(1).str.contains("reversed")
        flow_reversed = flow[flow_reversed_mask].rename(
            lambda x: x.replace("-reversed", "")
        )
        flow = flow[~flow_reversed_mask].subtract(flow_reversed, fill_value=0)

    # only line first index
    line_flow = flow.loc[flow.index.get_level_values(0).str.contains("Line")].copy().droplevel(0)
    link_flow = flow.loc[flow.index.get_level_values(0).str.contains("Link")].copy().droplevel(0)

    branch_components = ["Link"]
    if carrier == "AC":
        branch_components = ["Line", "Link"]

    ### Prices
    buses = n.buses.query("carrier in @carrier").index
    demand = n.statistics.energy_balance(bus_carrier=carrier, aggregate_time=False, groupby=["bus", "carrier"]).clip(lower=0).groupby("bus").sum().reindex(buses).rename(n.buses.location).T
    price = n.buses_t.marginal_price.reindex(buses, axis=1).rename(n.buses.location, axis=1)
    weighted_prices=(demand*price).sum()/demand.sum()
    weighted_prices = weighted_prices.dropna()

    if carrier == "co2 stored" and "CO2Limit" in n.global_constraints.index:
        co2_price = n.global_constraints.loc["CO2Limit", "mu"]
        weighted_prices = weighted_prices - co2_price

    # Set vmin and vmax for color mapping
    region_vmin = settings.get("region_vmin")
    region_vmax = settings.get("region_vmax")

    region_vmin = weighted_prices.min() if region_vmin is None else region_vmin
    region_vmax = weighted_prices.max() if region_vmax is None else region_vmax

    # Add prices to regions
    regions["price"] = weighted_prices.reindex(regions.index).fillna(0)

    regions["color"] = regions["price"].apply(
        price_to_color, 
        cmap=region_cmap,
        vmin=region_vmin,
        vmax=region_vmax,
        alpha=region_alpha,
    )

    # Create tooltips
    regions["tooltip_html"] = (
        "<b>" + regions.index + "</b><br>"
        +"<b>Weighted Price:</b> " + regions["price"].round(2).astype(str) + " " + region_unit
    )
    # regions["tooltip_html"] = regions["price"].round(2).astype(str) 
    # Create layer
    regions_layer = pdk.Layer(
        "GeoJsonLayer",
        regions,
        stroked=True,
        filled=True,
        get_fill_color="color",
        get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
    )

    map = n.explore(
        branch_components=branch_components,
        bus_size=bus_size.div(conversion),
        bus_split_circle=True,
        line_width=line_flow.div(conversion),
        line_flow=line_flow.div(conversion),
        line_color="rosybrown",
        link_width=link_flow.div(conversion),
        link_flow=link_flow.div(conversion),
        link_color=branch_color,
        arrow_size_factor=arrow_size_factor,
        tooltip=tooltip,
        auto_scale=True,
        branch_width_max=branch_width_max,
        bus_size_max=bus_size_max,
        map_style=map_style,
    )

    map.layers.insert(0, regions_layer)

    map.to_html(snakemake.output[0], offline=True)
