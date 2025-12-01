# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT


if config["foresight"] != "perfect":

    rule plot_base_network:
        params:
            plotting=config_provider("plotting"),
        input:
            network=resources("networks/base.nc"),
            regions_onshore=resources("regions_onshore.geojson"),
        output:
            map=resources("maps/power-network.pdf"),
        threads: 1
        resources:
            mem_mb=4000,
        benchmark:
            benchmarks("plot_base_network/base")
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_base_network.py"

    rule plot_power_network_clustered:
        params:
            plotting=config_provider("plotting"),
        input:
            network=resources("networks/base_s_{clusters}.nc"),
            regions_onshore=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            map=resources("maps/power-network-s-{clusters}.pdf"),
        threads: 1
        resources:
            mem_mb=4000,
        benchmark:
            benchmarks("plot_power_network_clustered/base_s_{clusters}")
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_power_network_clustered.py"

    rule plot_power_network:
        params:
            plotting=config_provider("plotting"),
            transmission_limit=config_provider("electricity", "transmission_limit"),
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            map=RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}-costs-all_{planning_horizons}.pdf",
        threads: 2
        resources:
            mem_mb=10000,
        log:
            RESULTS
            + "logs/plot_power_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
        benchmark:
            (
                RESULTS
                + "benchmarks/plot_power_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_power_network.py"

    rule plot_hydrogen_network:
        params:
            plotting=config_provider("plotting"),
            foresight=config_provider("foresight"),
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            map=RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}-h2_network_{planning_horizons}.pdf",
        threads: 2
        resources:
            mem_mb=10000,
        log:
            RESULTS
            + "logs/plot_hydrogen_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
        benchmark:
            (
                RESULTS
                + "benchmarks/plot_hydrogen_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_hydrogen_network.py"

    rule plot_gas_network:
        params:
            plotting=config_provider("plotting"),
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            map=RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}-ch4_network_{planning_horizons}.pdf",
        threads: 2
        resources:
            mem_mb=10000,
        log:
            RESULTS
            + "logs/plot_gas_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
        benchmark:
            (
                RESULTS
                + "benchmarks/plot_gas_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_gas_network.py"

    rule plot_balance_map:
        params:
            plotting=config_provider("plotting"),
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}-balance_map_{carrier}.pdf",
        threads: 1
        resources:
            mem_mb=8000,
        log:
            RESULTS
            + "logs/plot_balance_map/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{carrier}.log",
        benchmark:
            (
                RESULTS
                + "benchmarks/plot_balance_map/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{carrier}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_balance_map.py"


    rule plot_interactive_map:
        params:
            settings=lambda w: config_provider(
                "plotting", "interactive_map", w.carrier
            )
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            RESULTS
            + "maps/interactive/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}-interactive_map_{carrier}.html",
        threads: 1
        resources:
            mem_mb=8000,
        log:
            RESULTS
            + "logs/plot_interactive_map/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{carrier}.log",
        benchmark:
            (
                RESULTS
                + "benchmarks/plot_interactive_map/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{carrier}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_interactive_map.py"


if config["foresight"] == "perfect":

    def output_map_year(w):
        return {
            f"map_{year}": RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}-costs-all_"
            + f"{year}.pdf"
            for year in config_provider("scenario", "planning_horizons")(w)
        }

    rule plot_power_network_perfect:
        params:
            plotting=config_provider("plotting"),
        input:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_brownfield_all_years.nc",
            regions=resources("regions_onshore_base_s_{clusters}.geojson"),
        output:
            unpack(output_map_year),
        threads: 2
        resources:
            mem_mb=10000,
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/plot_power_network_perfect.py"


rule make_summary:
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
    output:
        nodal_costs=RESULTS
        + "csvs/individual/nodal_costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_capacities=RESULTS
        + "csvs/individual/nodal_capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_capacity_factors=RESULTS
        + "csvs/individual/nodal_capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        capacity_factors=RESULTS
        + "csvs/individual/capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        costs=RESULTS
        + "csvs/individual/costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        capacities=RESULTS
        + "csvs/individual/capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        curtailment=RESULTS
        + "csvs/individual/curtailment_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        energy=RESULTS
        + "csvs/individual/energy_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        energy_balance=RESULTS
        + "csvs/individual/energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_energy_balance=RESULTS
        + "csvs/individual/nodal_energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        prices=RESULTS
        + "csvs/individual/prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        weighted_prices=RESULTS
        + "csvs/individual/weighted_prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        market_values=RESULTS
        + "csvs/individual/market_values_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        metrics=RESULTS
        + "csvs/individual/metrics_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        price_time_series=RESULTS
        + "csvs/individual/price_time_series_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
    threads: 1
    resources:
        mem_mb=8000,
    log:
        RESULTS
        + "logs/make_summary_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
    benchmark:
        (
            RESULTS
            + "benchmarks/make_summary_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
        )
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_summary.py"


rule make_summary_regional:
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
    output:
        nodal_costs=RESULTS
        + "regional/csvs/{subregion}/individual/nodal_costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_capacities=RESULTS
        + "regional/csvs/{subregion}/individual/nodal_capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_capacity_factors=RESULTS
        + "regional/csvs/{subregion}/individual/nodal_capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        capacity_factors=RESULTS
        + "regional/csvs/{subregion}/individual/capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        costs=RESULTS
        + "regional/csvs/{subregion}/individual/costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        capacities=RESULTS
        + "regional/csvs/{subregion}/individual/capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        curtailment=RESULTS
        + "regional/csvs/{subregion}/individual/curtailment_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        energy=RESULTS
        + "regional/csvs/{subregion}/individual/energy_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        energy_balance=RESULTS
        + "regional/csvs/{subregion}/individual/energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        nodal_energy_balance=RESULTS
        + "regional/csvs/{subregion}/individual/nodal_energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        prices=RESULTS
        + "regional/csvs/{subregion}/individual/prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        weighted_prices=RESULTS
        + "regional/csvs/{subregion}/individual/weighted_prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        market_values=RESULTS
        + "regional/csvs/{subregion}/individual/market_values_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        metrics=RESULTS
        + "regional/csvs/{subregion}/individual/metrics_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
    threads: 1
    resources:
        mem_mb=8000,
    log:
        RESULTS
        + "logs/make_summary_regional_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{subregion}.log",
    benchmark:
        (
            RESULTS
            + "benchmarks/make_summary_regional_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_{subregion}"
        )
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_summary_regional.py"


rule make_global_summary:
    params:
        scenario=config_provider("scenario"),
        RDIR=RDIR,
    input:
        nodal_costs=expand(
            RESULTS
            + "csvs/individual/nodal_costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_capacities=expand(
            RESULTS
            + "csvs/individual/nodal_capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_capacity_factors=expand(
            RESULTS
            + "csvs/individual/nodal_capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        capacity_factors=expand(
            RESULTS
            + "csvs/individual/capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        costs=expand(
            RESULTS
            + "csvs/individual/costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        capacities=expand(
            RESULTS
            + "csvs/individual/capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        curtailment=expand(
            RESULTS
            + "csvs/individual/curtailment_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        energy=expand(
            RESULTS
            + "csvs/individual/energy_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        energy_balance=expand(
            RESULTS
            + "csvs/individual/energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_energy_balance=expand(
            RESULTS
            + "csvs/individual/nodal_energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        prices=expand(
            RESULTS
            + "csvs/individual/prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        weighted_prices=expand(
            RESULTS
            + "csvs/individual/weighted_prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        market_values=expand(
            RESULTS
            + "csvs/individual/market_values_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
        metrics=expand(
            RESULTS
            + "csvs/individual/metrics_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            allow_missing=True,
        ),
    output:
        costs=RESULTS + "csvs/costs.csv",
        capacities=RESULTS + "csvs/capacities.csv",
        energy=RESULTS + "csvs/energy.csv",
        energy_balance=RESULTS + "csvs/energy_balance.csv",
        capacity_factors=RESULTS + "csvs/capacity_factors.csv",
        metrics=RESULTS + "csvs/metrics.csv",
        curtailment=RESULTS + "csvs/curtailment.csv",
        prices=RESULTS + "csvs/prices.csv",
        weighted_prices=RESULTS + "csvs/weighted_prices.csv",
        market_values=RESULTS + "csvs/market_values.csv",
        nodal_costs=RESULTS + "csvs/nodal_costs.csv",
        nodal_capacities=RESULTS + "csvs/nodal_capacities.csv",
        nodal_energy_balance=RESULTS + "csvs/nodal_energy_balance.csv",
        nodal_capacity_factors=RESULTS + "csvs/nodal_capacity_factors.csv",
    threads: 1
    resources:
        mem_mb=8000,
    log:
        RESULTS + "logs/make_global_summary.log",
    benchmark:
        RESULTS + "benchmarks/make_global_summary"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_global_summary.py"


rule make_global_summary_regional:
    params:
        scenario=config_provider("scenario"),
        RDIR=RDIR,
    input:
        nodal_costs=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/nodal_costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_capacities=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/nodal_capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_capacity_factors=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/nodal_capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        capacity_factors=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/capacity_factors_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        costs=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/costs_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        capacities=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/capacities_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        curtailment=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/curtailment_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        energy=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/energy_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        energy_balance=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        nodal_energy_balance=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/nodal_energy_balance_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        prices=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        weighted_prices=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/weighted_prices_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        market_values=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/market_values_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
        metrics=expand(
            RESULTS
            + "regional/csvs/{subregion}/individual/metrics_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            subregion=config_provider("regional_summary", "subregions"),
            **config["scenario"],
            allow_missing=True,
        ),
    output:
        costs=RESULTS + "regional/csvs/{subregion}/costs.csv",
        capacities=RESULTS + "regional/csvs/{subregion}/capacities.csv",
        energy=RESULTS + "regional/csvs/{subregion}/energy.csv",
        energy_balance=RESULTS + "regional/csvs/{subregion}/energy_balance.csv",
        capacity_factors=RESULTS + "regional/csvs/{subregion}/capacity_factors.csv",
        metrics=RESULTS + "regional/csvs/{subregion}/metrics.csv",
        curtailment=RESULTS + "regional/csvs/{subregion}/curtailment.csv",
        prices=RESULTS + "regional/csvs/{subregion}/prices.csv",
        weighted_prices=RESULTS + "regional/csvs/{subregion}/weighted_prices.csv",
        market_values=RESULTS + "regional/csvs/{subregion}/market_values.csv",
        nodal_costs=RESULTS + "regional/csvs/{subregion}/nodal_costs.csv",
        nodal_capacities=RESULTS + "regional/csvs/{subregion}/nodal_capacities.csv",
        nodal_energy_balance=RESULTS + "regional/csvs/{subregion}/nodal_energy_balance.csv",
        nodal_capacity_factors=RESULTS + "regional/csvs/{subregion}/nodal_capacity_factors.csv",
    threads: 1
    resources:
        mem_mb=8000,
    log:
        RESULTS + "logs/make_global_summary_regional_{subregion}.log",
    benchmark:
        RESULTS + "benchmarks/make_global_summary_regional_{subregion}"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_global_summary_regional.py"


rule make_cumulative_costs:
    params:
        scenario=config_provider("scenario"),
    input:
        costs=RESULTS + "csvs/costs.csv",
    output:
        cumulative_costs=RESULTS + "csvs/cumulative_costs.csv",
    threads: 1
    resources:
        mem_mb=4000,
    log:
        RESULTS + "logs/make_cumulative_costs.log",
    benchmark:
        RESULTS + "benchmarks/make_cumulative_costs"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_cumulative_costs.py"


rule make_cumulative_costs_regional:
    params:
        scenario=config_provider("scenario"),
    input:
        costs=RESULTS + "regional/csvs/{subregion}/costs.csv",
    output:
        cumulative_costs=RESULTS + "regional/csvs/{subregion}/cumulative_costs.csv",
    threads: 1
    resources:
        mem_mb=4000,
    log:
        RESULTS + "logs/make_cumulative_costs_regional_{subregion}.log",
    benchmark:
        RESULTS + "benchmarks/make_cumulative_costs_regional_{subregion}"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/make_cumulative_costs.py"


rule plot_summary:
    params:
        countries=config_provider("countries"),
        planning_horizons=config_provider("scenario", "planning_horizons"),
        emissions_scope=config_provider("energy", "emissions"),
        plotting=config_provider("plotting"),
        foresight=config_provider("foresight"),
        co2_budget=config_provider("co2_budget"),
        sector=config_provider("sector"),
        RDIR=RDIR,
    input:
        costs=RESULTS + "csvs/costs.csv",
        energy=RESULTS + "csvs/energy.csv",
        balances=RESULTS + "csvs/energy_balance.csv",
        eurostat="data/eurostat/Balances-April2023",
        co2="data/bundle/eea/UNFCCC_v23.csv",
    output:
        costs=RESULTS + "graphs/costs.svg",
        energy=RESULTS + "graphs/energy.svg",
        balances=RESULTS + "graphs/balances-energy.svg",
    threads: 2
    resources:
        mem_mb=10000,
    log:
        RESULTS + "logs/plot_summary.log",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_summary.py"


rule plot_summary_regional:
    params:
        countries=config_provider("countries"),
        planning_horizons=config_provider("scenario", "planning_horizons"),
        emissions_scope=config_provider("energy", "emissions"),
        plotting=config_provider("plotting"),
        foresight=config_provider("foresight"),
        co2_budget=config_provider("co2_budget"),
        sector=config_provider("sector"),
        RDIR=RDIR,
    input:
        costs=RESULTS + "regional/csvs/{subregion}/costs.csv",
        energy=RESULTS + "regional/csvs/{subregion}/energy.csv",
        balances=RESULTS + "regional/csvs/{subregion}/energy_balance.csv",
        eurostat="data/eurostat/Balances-April2023",
        co2="data/bundle/eea/UNFCCC_v23.csv",
    output:
        costs=RESULTS + "regional/graphs/{subregion}/costs.svg",
        energy=RESULTS + "regional/graphs/{subregion}/energy.svg",
        balances=RESULTS + "regional/graphs/{subregion}/balances-energy.svg",
    threads: 2
    resources:
        mem_mb=10000,
    log:
        RESULTS + "logs/plot_summary_regional_{subregion}.log",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_summary.py"


rule plot_balance_timeseries:
    params:
        plotting=config_provider("plotting"),
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        rc="matplotlibrc",
    threads: 16
    resources:
        mem_mb=10000,
    log:
        RESULTS
        + "logs/plot_balance_timeseries/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
    benchmark:
        RESULTS
        +"benchmarks/plot_balance_timeseries/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
    conda:
        "../envs/environment.yaml"
    output:
        directory(
            RESULTS
            + "graphics/balance_timeseries/s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
        ),
    script:
        "../scripts/plot_balance_timeseries.py"


rule plot_heatmap_timeseries:
    params:
        plotting=config_provider("plotting"),
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        rc="matplotlibrc",
    threads: 16
    resources:
        mem_mb=10000,
    log:
        RESULTS
        + "logs/plot_heatmap_timeseries/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.log",
    benchmark:
        RESULTS
        +"benchmarks/plot_heatmap_timeseries/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
    conda:
        "../envs/environment.yaml"
    output:
        directory(
            RESULTS
            + "graphics/heatmap_timeseries/s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
        ),
    script:
        "../scripts/plot_heatmap_timeseries.py"


STATISTICS_BARPLOTS = [
    "capacity_factor",
    "installed_capacity",
    "optimal_capacity",
    "capital_expenditure",
    "operational_expenditure",
    "curtailment",
    "supply",
    "withdrawal",
    "market_value",
]

STATISTICS = {
    "capacity_factor": ("-", "p.u."),
    "installed_capacity": (1e3, "GW"),
    "optimal_capacity": (1e3, "GW"),
    "capex": (1e9, "bn €"),
    "opex": (1e9, "bn €"),
    "total_cost": ("1e9", "bn €"),
    "curtailment": (1e3, "GWh"),
    "supply": (1e6, "TWh"),
    "withdrawal": (1e6, "TWh"),
    "energy_balance": (1e6, "TWh"),
    "market_value": ("-", "€/MWh"),
}


rule write_statistics:
    params:
        statistics=STATISTICS,
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
    output:
        **{
            f"{csv}": RESULTS
            + "statistics/csv/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/{carrier}_"
            + f"{csv}.csv"
            for carrier in config["plotting"].get("carriers", "all")
            for csv in STATISTICS
        },
        csv_touch=RESULTS
        + "statistics/csv/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/.statistics_{carrier}_csv",
    log:
        RESULTS
        + "logs/write_statistics/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_country-{country}_carrier-{carrier}.log",
    script:
        "../scripts/write_statistics.py"


rule plot_statistics_single:
    params:
        plotting=config["plotting"],
        statistics=STATISTICS,
    input:
        **{
            f"{csv}": RESULTS
            + "statistics/csv/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/{carrier}_"
            + f"{csv}.csv"
            for carrier in config["plotting"].get("carriers", "all")
            for csv in STATISTICS
        },
    output:
        **{
            f"{plot}": RESULTS
            + "statistics/figures/single/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/{carrier}_"
            + f"{plot}.pdf"
            for carrier in config["plotting"].get("carriers", "all")
            for plot in STATISTICS
        },
        barplots_touch=RESULTS
        + "statistics/figures/single/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/.statistics_{carrier}_plots",
    log:
        RESULTS
        + "logs/plot_statistics_single/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_country-{country}_carrier-{carrier}.log",
    script:
        "../scripts/plot_statistics_single.py"


rule plot_statistics_comparison:
    params:
        plotting=config["plotting"],
        statistics=STATISTICS,
    input:
        expand(
            RESULTS
            + "statistics/csv/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}/country_{country}/{carrier}_{csv}.csv",
            **config["scenario"],
            csv=STATISTICS,
            allow_missing=True,
        ),
    output:
        **{
            f"{plot}": RESULTS
            + "statistics/figures/comparison/country_{country}/{carrier}_"
            + f"{plot}.pdf"
            for carrier in config["plotting"].get("carriers", "all")
            for plot in STATISTICS
        },
        barplots_touch=RESULTS
        + "statistics/figures/comparison/country_{country}/.statistics_{carrier}_plots",
    log:
        RESULTS
        + "logs/plot_statistics_comparison/country-{country}_carrier-{carrier}.log",
    script:
        "../scripts/plot_statistics_comparison.py"


rule plot_base_statistics:
    params:
        plotting=config_provider("plotting"),
        barplots=STATISTICS_BARPLOTS,
    input:
        network=RESULTS + "networks/base_s_{clusters}_elec_{opts}.nc",
    output:
        **{
            f"{plot}_bar": RESULTS
            + f"figures/statistics_{plot}_bar_base_s_{{clusters}}_elec_{{opts}}.pdf"
            for plot in STATISTICS_BARPLOTS
        },
        barplots_touch=RESULTS
        + "figures/.statistics_plots_base_s_{clusters}_elec_{opts}",
    script:
        "../scripts/plot_statistics.py"


rule plot_costs_overview:
    params:
        plotting_fig=config_provider("plotting", "figures", "plot_costs_overview"),
    input:
        costs=expand(
            RESULTS + "csvs/costs.csv",
            **config["scenario"],
            run=config["run"]["name"],
        ),
    output:
        plot="results/" + PREFIX+"/graphs/costs_overview.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_costs_overview.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_costs_overview",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_costs_overview.py"


rule plot_costs_overview_regional:
    params:
        plotting_fig=config_provider("plotting", "figures", "plot_costs_overview"),
    input:
        costs=lambda w: expand(
            RESULTS + "regional/csvs/{subregion}/costs.csv",
            **config["scenario"],
            run=config["run"]["name"],
            subregion=w.subregion
        )
    output:
        plot="results/" + PREFIX+"/graphs/costs_overview_{subregion}.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_costs_overview_{subregion}.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_costs_overview_{subregion}",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_costs_overview.py"


rule plot_delta_costs_overview:
    params:
        plotting_fig=config_provider("plotting", "figures", "plot_delta_costs_overview"),
    input:
        costs=expand(
            RESULTS + "csvs/costs.csv",
            **config["scenario"],
            run=config["run"]["name"],
        ),
    output:
        plot="results/" + PREFIX+"/graphs/delta_costs_overview.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_delta_costs_overview.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_delta_costs_overview",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_delta_costs_overview.py"


rule plot_delta_costs_overview_regional:
    params:
        plotting_fig=config_provider("plotting", "figures", "plot_delta_costs_overview"),
    input:
        costs=lambda w: expand(
            RESULTS + "regional/csvs/{subregion}/costs.csv",
            **config["scenario"],
            run=config["run"]["name"],
            subregion=w.subregion
        )
    output:
        plot="results/" + PREFIX+"/graphs/delta_costs_overview_{subregion}.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_delta_costs_overview_{subregion}.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_delta_costs_overview_{subregion}",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_delta_costs_overview.py"


def input_european_co2_pipelines(w):
    european_co2_pipelines = config_provider("sector", "european_co2_pipelines")(w)
    if european_co2_pipelines["enable"]:
        inputs= {
            "buses_offshore": resources("european_co2_pipelines/buses_offshore_s_{clusters}_{opts}.csv"),
            "links_co2_pipeline": resources("european_co2_pipelines/links_co2_pipeline_s_{clusters}_{opts}.csv"),
            "stores_co2": resources("european_co2_pipelines/stores_co2_s_{clusters}_{opts}.csv"),
        }
    else :
        inputs= {
            "buses_offshore": [],
            "links_co2_pipeline": [],
            "stores_co2": [],
        }
    return inputs


rule plot_map:
    params:
        plotting_all=config_provider("plotting", "all"),
        plotting_fig=config_provider("plotting", "figures", "plot_pcipmi_map"),
        salt_cavern_settings=config_provider("sector", "hydrogen_underground_storage_locations"),
    input:
        unpack(input_european_co2_pipelines),
        regions_onshore = resources("regions_onshore_base_s_{clusters}.geojson"),
        regions_offshore = resources("regions_offshore_base_s_{clusters}.geojson"),
        sequestration_potential=resources(
            "co2_sequestration_potential_base_s_{clusters}.geojson"
        ),
    output:
        map= "results/" + PREFIX+"/maps/map_{clusters}_{run}.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_pcipmi_map_{clusters}_{run}.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_pcipmi_map_{clusters}_{run}",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_map.py"


rule plot_balances_overview:
    params:
        plotting_fig=config_provider("plotting", "figures", "plot_balances_overview"),
    input:
        balances=expand(
            RESULTS + "csvs/energy_balance.csv",
            **config["scenario"],
            run=config["run"]["name"],
        ),
    output:
        plot= "results/" + PREFIX+"/graphs/balances_overview_{carrier}.pdf",
    log:
        "results/" + PREFIX + "/logs/plot_balances_overview_{carrier}.log",
    benchmark:
        "results/" + PREFIX + "/benchmark/plot_balances_overview_{carrier}",
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_balances_overview.py"


rule plot_price_progressions:
    input:
        lambda w: expand(
            RESULTS + "csvs/individual/price_time_series_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            **config["scenario"],
            run=w.run,
        )
    output:
        plot = RESULTS + "graphs/price_progressions_s_{clusters}_{opts}_{sector_opts}.pdf"
    log:
        RESULTS + "logs/plot_price_progressions/base_s_{clusters}_{opts}_{sector_opts}.log"
    benchmark:
        RESULTS + "benchmarks/plot_price_progressions/base_s_{clusters}_{opts}_{sector_opts}"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/plot_price_progressions.py"