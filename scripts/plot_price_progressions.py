# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts._helpers import (
    configure_logging,
    set_scenario_config,
)

def truncate_to_95pct(x):
    lo = np.percentile(x, 2.5)
    hi = np.percentile(x, 97.5)
    return x[(x >= lo) & (x <= hi)]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "plot_price_progressions",
            configfiles=["config/config.nrw-workshop.yaml"],
            clusters="adm",
            opts="",
            sector_opts="",
            run="forecast-delayed-co2-pipelines-min-ccs",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    dfs = []
    for price_file in snakemake.input:   # if input is a dict
        year = int(price_file.rsplit("_", 1)[-1].split(".", 1)[0])
        df = pd.read_csv(price_file, index_col=0)
        df["year"] = year
        df = df.loc[df.index.repeat(df["snapshot_weight"])].reset_index(drop=True)


        # Update CO2 prices to include emission price
        emission_price = df["co2"].mean()
        df["co2 sequestered"] = df["co2 sequestered"] - emission_price
        df["co2 stored"] = df["co2 stored"] - emission_price
        # Turn Co2 into abs value
        df["co2"] = df["co2"].abs()

        dfs.append(df)

    price_dfs = pd.concat(dfs, ignore_index=True)

    ###################################
    # Multi-column violin figure: 5 carriers
    ###################################

    carriers = ["AC", "H2", "co2 stored", "co2 sequestered", "co2"]

    # Colors
    colors = {
        "AC": "#3CB043",               # green
        "H2": "#FF77C9",               # pink
        "co2": "#FF8C00",              # orange
        "co2 stored": "#FFA74F",       # light orange
        "co2 sequestered": "#FFD1A1",  # very light orange
    }

    years = sorted(price_dfs["year"].unique())

    fig, axes = plt.subplots(
        nrows=1,
        ncols=len(carriers),
        figsize=(2.5 * len(carriers), 4),
        sharey=False,
        sharex=False
    )

    for ax, carrier in zip(axes, carriers):

        # Build truncated groups for this carrier
        groups = [
            truncate_to_95pct(g[carrier].to_numpy())
            for _, g in price_dfs.groupby("year")
        ]

        parts = ax.violinplot(
            groups,
            showmeans=True,
            showextrema=True,
        )

        # Color the violins
        for body in parts["bodies"]:
            body.set_facecolor(colors[carrier])
            body.set_edgecolor("black")
            body.set_alpha(0.8)

        # Color lines (mean, whiskers)
        for key in ["cmeans", "cmins", "cmaxes", "cbars"]:
            if key in parts:
                parts[key].set_color("black")
                parts[key].set_linewidth(1.0)

        # X-axis years
        ax.set_xticks(range(1, len(years) + 1))
        ax.set_xticklabels(years, rotation=45, ha="right")

        # Title above each column
        ax.set_title(carrier)

    # Shared x-label centered under the whole figure
    fig.supxlabel("Year", y=0.02)

    plt.tight_layout()
    plt.show()

