# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

"""
Plots the PCI-PMI CO2 and H2 infrastructure on a map
"""

import logging

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import geopandas as gpd

from scripts._helpers import configure_logging, set_scenario_config
from shapely import wkt
from shapely.geometry import LineString

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "plot_map",
            clusters="adm",
            opts="",
            configfiles=["config/config.nrw-workshop.yaml"],
            run="forecast-co2-pipelines-max-ccs",
            )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    rule = snakemake.rule
    config = snakemake.config
    plotting = snakemake.params.plotting_fig

    figsize = (6,4)
    fontsize = 10
    titlesize = fontsize
    dpi = 150

    salt_cavern_settings = snakemake.params.salt_cavern_settings

    # Read input files
    regions_onshore = gpd.read_file(snakemake.input.regions_onshore)
    regions_offshore = gpd.read_file(snakemake.input.regions_offshore)
    sequestration_potential = gpd.read_file(snakemake.input.sequestration_potential)
    links_co2_pipeline = gpd.read_file(snakemake.input.links_co2_pipeline)
    links_co2_pipeline["geometry"] = links_co2_pipeline["geometry"].apply(wkt.loads)
    links_co2_pipeline = gpd.GeoDataFrame(links_co2_pipeline, geometry="geometry", crs="EPSG:3035").to_crs("EPSG:4326")
    stores_co2 = gpd.read_file(snakemake.input.stores_co2)
    stores_co2["geometry"] = stores_co2["geometry"].apply(wkt.loads)
    stores_co2 = gpd.GeoDataFrame(stores_co2, geometry="geometry", crs="EPSG:3035").to_crs("EPSG:4326")

    # Update linestrings for onshore grid
    onshore_points = regions_onshore.copy()
    onshore_points["geometry"] = onshore_points["geometry"].representative_point()
    # Map bus points
    lookup = onshore_points.set_index("name")["geometry"]
    links_co2_pipeline["bus0_geom"] = links_co2_pipeline["bus0"].map(lookup)
    links_co2_pipeline["bus1_geom"] = links_co2_pipeline["bus1"].map(lookup)

    # Create new LineString
    def create_linestring(row):
        if row["bus0_geom"] is not None and row["bus1_geom"] is not None:
            return LineString([row["bus0_geom"], row["bus1_geom"]])
        else:
            return row["geometry"]

    links_co2_pipeline["geometry"] = links_co2_pipeline.apply(create_linestring, axis=1)

    alpha_regions = 0.3
    alpha_links = 0.8
    alpha_stores = 0.8
    alpha_gridlines = 0.5
    alpha_seq = 0.8

    # Create map
    crs = ccrs.EqualEarth()

    color_co2 = "darkred"
    color_seq = "orange"

    fig, ax = plt.subplots(1, 1, figsize=figsize, subplot_kw={'projection': crs})

    # plt.rc("font", **plotting["font"])

    # Add regions
    regions_onshore.to_crs(crs.proj4_init).plot(ax=ax, color="lightgrey", edgecolor="black", linewidth=0.5, alpha=alpha_regions)
    regions_offshore.to_crs(crs.proj4_init).plot(ax=ax, color="lightblue", edgecolor="black", linewidth=0.5, alpha=alpha_regions)

    # Add gridlines 
    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=True,
        linewidth=0.5,
        color='gray',
        alpha=0.5,
        linestyle=':',
    )

    # Label style
    gl.xlabel_style = {"size": fontsize}
    gl.ylabel_style = {"size": fontsize}

    # Show only bottom and right labels
    gl.top_labels = False
    gl.left_labels = False
    gl.bottom_labels = True
    gl.right_labels = True

    # Move labels inside
    gl.xpadding = -1
    gl.ypadding = -1

    # Set finer gridline spacing
    gl.xlocator = plt.FixedLocator(range(-180, 181, 5))  # e.g., every 15°
    gl.ylocator = plt.FixedLocator(range(-90, 91, 5)) 

    # Add projects
    sequestration_potential.to_crs(crs.proj4_init).buffer(8000).plot(ax=ax, color=color_seq, edgecolor=None, linewidth=0.5, alpha=alpha_seq, zorder=5)
    links_co2_pipeline.to_crs(crs.proj4_init).plot(ax=ax, color=color_co2, linewidth=1, alpha=alpha_links, zorder=10)
    stores_co2.to_crs(crs.proj4_init).plot(ax=ax, color=color_co2, edgecolor=None, linewidth=0.5, alpha=alpha_stores, zorder=20, markersize=20)
    
    # Create a legend for the pipelines
    # Legend handles
    # Legend handles
    legend_links_co2 = plt.Line2D([0], [0], color=color_co2, linewidth=1.5, alpha=alpha_links)

    legend_stores_co2 = plt.Line2D(
        [0], [0],
        marker="o",
        linewidth=0,
        color=color_co2,
        markersize=5,
        alpha=alpha_stores,
        markeredgewidth=0
    )
    legend_seq = plt.Line2D(
        [0], [0],
        marker="s",
        linewidth=0,
        color=color_seq,
        markersize=5,
        alpha=alpha_seq,
        markeredgewidth=0
    )

    # Legend labels
    name_links_co2 = "Planned CO$_2$ pipelines"
    name_stores_co2 = "Planned CO$_2$ sequestration"
    name_seq = "Add. offshore sequestration potential"

    # Add legend
    ax.legend(
        [
            legend_links_co2,
            legend_stores_co2,
            legend_seq,
        ],
        [
            name_links_co2,
            name_stores_co2,
            name_seq,
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.01),
        ncol=1,
        fontsize=fontsize,
        frameon=False,
        handlelength=1.2,   # shorter line length
        # handletextpad=0.4,  # smaller space between symbol and label
        # columnspacing=0.8,  # compact column spacing
    )
    boundaries = [-6, 20, 42, 68]   # [west_lon, east_lon, south_lat, north_lat]
    ax.set_extent(boundaries, crs=ccrs.PlateCarree())

    # Save figure
    fig.savefig(
        snakemake.output[0],
        bbox_inches="tight",
        dpi=dpi,
    )
