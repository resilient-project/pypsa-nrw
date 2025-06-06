#!/usr/bin/env python3
# SPDX-FileCopyrightText: : 2017-2023 The PyPSA-Eur Authors
#
# SPDX-License-Identifier: MIT

import logging

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from scripts._helpers import configure_logging
from scripts.plot_summary import rename_techs

logger = logging.getLogger(__name__)
sns.set_theme("paper", style="whitegrid")
STACKED = {
    "capacity_factor": False,
    "market_value": False,
}


def rename_index(df):
    # rename index and drop duplicates
    specific = df.index.map(lambda x: f"{x[1]}({x[0]})")
    generic = df.index.get_level_values("carrier")
    duplicated = generic.duplicated(keep=False)
    index = specific.where(duplicated, generic)
    df = df.set_axis(index)
    # rename columns and drop duplicates
    columns = df.columns.str.split("_", expand=True)
    columns = [
        columns.get_level_values(level).unique()
        for level in range(columns.nlevels)
        if not columns.get_level_values(level).duplicated(keep=False).all()
    ]
    columns = pd.MultiIndex.from_arrays(columns)
    df.columns = columns.map("\n".join)
    return df


def plot_static_comparison(df, ax, stacked=False):
    factor, unit = conversion[output]
    df = df[df != 0]
    df = df.dropna(axis=0, how="all").fillna(0)
    if df.empty:
        return
    df = df.rename(index=rename_techs).groupby(["component", "carrier"]).sum()
    carriers = df.index.get_level_values("carrier")
    if not carriers.difference(tech_colors.index).empty:
        print(
            f"Missing colors for carrier: {carriers.difference(tech_colors.index).values}\n Dark grey used instead."
        )
    c = carriers.map(lambda x: tech_colors.get(x, "#808080"))
    df = df.pipe(rename_index).T
    df = df.div(float(factor)) if factor != "-" else df
    df.plot.bar(color=c.values, ax=ax, stacked=stacked, legend=False, ylabel=unit)
    ax.legend(
        bbox_to_anchor=(1, 1),
        loc="upper left",
    )
    ax.grid(axis="x")


def read_csv(input, output):
    try:
        # filter required csv to plot the wanted output
        files = list(filter(lambda x: output in x, input))
        # retrieves network labels from folder name
        network_labels = [file.split("/")[-3] for file in files]
        df = pd.concat(
            [
                pd.read_csv(f, skiprows=2).set_index(["component", "carrier"])
                for f in files
            ],
            axis=1,
            keys=network_labels,
        )
        # get plot label and drop from index
        df.columns = df.columns.droplevel(1)
    except Exception as e:
        print(f"Error reading csv file for {output}: {e}")
        df = pd.DataFrame()
    return df


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "plot_statistics_comparison",
            run="ExPol",
            country="DE",
            carrier="H2",
        )

    configure_logging(snakemake)

    tech_colors = pd.Series(snakemake.params.plotting["tech_colors"])
    conversion = pd.Series(snakemake.params.statistics)

    for output in snakemake.output.keys():
        if "touch" in output:
            with open(snakemake.output.barplots_touch, "a"):
                pass
                continue
        fig, ax = plt.subplots()
        df = read_csv(snakemake.input, output)
        if df.empty:
            ax.text(
                0.5,
                0.5,
                "No data available.",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=14,
                color="red",
            )
            fig.savefig(snakemake.output[output])
            continue

        plot_static_comparison(df, ax, stacked=STACKED.get(output, True))

        fig.savefig(snakemake.output[output], bbox_inches="tight")
