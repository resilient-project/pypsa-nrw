# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Adds existing power and heat generation capacities for initial planning
horizon.
"""

import logging
import re
from types import SimpleNamespace

import country_converter as coco
import numpy as np
import pandas as pd
import powerplantmatching as pm
import pypsa
import xarray as xr

from scripts._helpers import (
    configure_logging,
    sanitize_custom_columns,
    set_scenario_config,
    update_config_from_wildcards,
)
from scripts.add_electricity import load_costs, sanitize_carriers
from scripts.build_energy_totals import cartesian
from scripts.build_powerplants import add_custom_powerplants
from scripts.definitions.heat_system import HeatSystem
from scripts.prepare_sector_network import (
    cluster_heat_buses,
    define_spatial,
)

logger = logging.getLogger(__name__)
cc = coco.CountryConverter()
idx = pd.IndexSlice
spatial = SimpleNamespace()


def add_build_year_to_new_assets(n: pypsa.Network, baseyear: int) -> None:
    """
    Add build year to new assets in the network.

    Parameters
    ----------
    n : pypsa.Network
        Network to modify
    baseyear : int
        Year in which optimized assets are built
    """
    # Give assets with lifetimes and no build year the build year baseyear
    for c in n.iterate_components(["Link", "Generator", "Store"]):
        assets = c.df.index[(c.df.lifetime != np.inf) & (c.df.build_year == 0)]
        c.df.loc[assets, "build_year"] = baseyear

        # add -baseyear to name
        rename = pd.Series(c.df.index, c.df.index)
        rename[assets] += f"-{str(baseyear)}"
        c.df.rename(index=rename, inplace=True)

        # rename time-dependent
        selection = n.component_attrs[c.name].type.str.contains(
            "series"
        ) & n.component_attrs[c.name].status.str.contains("Input")
        for attr in n.component_attrs[c.name].index[selection]:
            c.pnl[attr] = c.pnl[attr].rename(columns=rename)


def add_existing_renewables(
    n: pypsa.Network,
    costs: pd.DataFrame,
    df_agg: pd.DataFrame,
    countries: list[str],
) -> None:
    """
    Add existing renewable capacities to conventional power plant data.

    Parameters
    ----------
    df_agg : pd.DataFrame
        DataFrame containing conventional power plant data
    costs : pd.DataFrame
        Technology cost data with 'lifetime' column indexed by technology
    n : pypsa.Network
        Network containing topology and generator data
    countries : list
        List of country codes to consider

    Returns
    -------
    None
        Modifies df_agg in-place
    """
    tech_map = {"solar": "PV", "onwind": "Onshore", "offwind-ac": "Offshore"}

    irena = pm.data.IRENASTAT().powerplant.convert_country_to_alpha2()
    irena = irena.query("Country in @countries")
    irena = irena.groupby(["Technology", "Country", "Year"]).Capacity.sum()

    irena = irena.unstack().reset_index()

    for carrier, tech in tech_map.items():
        df = (
            irena[irena.Technology.str.contains(tech)]
            .drop(columns=["Technology"])
            .set_index("Country")
        )
        df.columns = df.columns.astype(int)

        # calculate yearly differences
        df.insert(loc=0, value=0.0, column="1999")
        df = df.diff(axis=1).drop("1999", axis=1).clip(lower=0)

        # distribute capacities among generators potential (p_nom_max)
        gen_i = n.generators.query("carrier == @carrier").index
        carrier_gens = n.generators.loc[gen_i]
        res_capacities = []
        for country, group in carrier_gens.groupby(
            carrier_gens.bus.map(n.buses.country)
        ):
            fraction = group.p_nom_max / group.p_nom_max.sum()
            res_capacities.append(cartesian(df.loc[country], fraction))
        res_capacities = pd.concat(res_capacities, axis=1).T

        for year in res_capacities.columns:
            for gen in res_capacities.index:
                bus_bin = re.sub(f" {carrier}.*", "", gen)
                bus, bin_id = bus_bin.rsplit(" ", maxsplit=1)
                name = f"{bus_bin} {carrier}-{year}"
                capacity = res_capacities.loc[gen, year]
                if capacity > 0.0:
                    cost_key = carrier.split("-", maxsplit=1)[0]
                    df_agg.at[name, "Fueltype"] = carrier
                    df_agg.at[name, "Capacity"] = capacity
                    df_agg.at[name, "DateIn"] = year
                    df_agg.at[name, "lifetime"] = costs.at[cost_key, "lifetime"]
                    df_agg.at[name, "DateOut"] = (
                        year + costs.at[cost_key, "lifetime"] - 1
                    )
                    df_agg.at[name, "bus"] = bus
                    df_agg.at[name, "resource_class"] = bin_id

    df_agg["resource_class"] = df_agg["resource_class"].fillna(0)


def add_power_capacities_installed_before_baseyear(
    n: pypsa.Network,
    costs: pd.DataFrame,
    grouping_years: list[int],
    baseyear: int,
    powerplants_file: str,
    countries: list[str],
    capacity_threshold: float,
    lifetime_values: dict[str, float],
) -> None:
    """
    Add power generation capacities installed before base year.

    Parameters
    ----------
    n : pypsa.Network
        Network to modify
    costs : pd.DataFrame
        Technology costs
    grouping_years : list
        Intervals to group existing capacities
    baseyear : int
        Base year for analysis
    powerplants_file : str
        Path to powerplants CSV file
    countries : list
        List of countries to consider
    capacity_threshold : float
        Minimum capacity threshold
    lifetime_values : dict
        Default values for missing data
    """
    logger.debug(f"Adding power capacities installed before {baseyear}")

    df_agg = pd.read_csv(powerplants_file, index_col=0)

    if snakemake.input.get("custom_powerplants"):
        df_agg = add_custom_powerplants(
            df_agg, snakemake.input.custom_powerplants, True
        )

    rename_fuel = {
        "Hard Coal": "coal",
        "Lignite": "lignite",
        "Nuclear": "nuclear",
        "Oil": "oil",
        "OCGT": "OCGT",
        "CCGT": "CCGT",
        "Bioenergy": "solid biomass",
    }

    # If heat is considered, add CHPs in the add_heating_capacities function.
    # Assume that all oil power plants are not CHPs.
    if options["heating"]:
        df_agg = df_agg.query("Set != 'CHP'")
    elif not options["industry"] and "Industry" in df_agg.columns:
        df_agg["Industry"].fillna(False, inplace=True)
        df_agg.query("not Industry", inplace=True)

    # Replace Fueltype "Natural Gas" with the respective technology (OCGT or CCGT)
    natural_gas_mask = df_agg["Fueltype"] == "Natural Gas"
    df_agg.loc[natural_gas_mask, "Fueltype"] = df_agg.loc[
        natural_gas_mask, "Technology"
    ]

    fueltype_to_drop = [
        "Hydro",
        "Wind",
        "Solar",
        "Geothermal",
        "Waste",
        "Other",
        "CCGT, Thermal",
    ]

    technology_to_drop = ["Pv", "Storage Technologies"]

    # drop unused fueltypes and technologies
    df_agg = df_agg[~df_agg["Fueltype"].isin(fueltype_to_drop)]
    df_agg = df_agg[~df_agg["Technology"].isin(technology_to_drop)]
    df_agg["Fueltype"] = df_agg["Fueltype"].map(rename_fuel)

    # Intermediate fix for DateIn & DateOut
    # Fill missing DateIn
    biomass_i = df_agg.loc[df_agg.Fueltype == "solid biomass"].index
    mean = df_agg.loc[biomass_i, "DateIn"].mean()
    df_agg.loc[biomass_i, "DateIn"] = df_agg.loc[biomass_i, "DateIn"].fillna(int(mean))
    # Fill missing DateOut
    dateout = df_agg.loc[biomass_i, "DateIn"] + lifetime_values["lifetime"]
    df_agg.loc[biomass_i, "DateOut"] = df_agg.loc[biomass_i, "DateOut"].fillna(dateout)

    # split biogas and solid biomass
    biogas_i = biomass_i.intersection(df_agg.loc[df_agg.Capacity < 2].index)
    df_agg.loc[biogas_i, "Fueltype"] = "biogas"

    # include renewables in df_agg
    add_existing_renewables(
        df_agg=df_agg,
        costs=costs,
        n=n,
        countries=countries,
    )

    # add chp plants
    add_chp_plants(n, grouping_years, costs, baseyear)

    # drop assets which are already phased out / decommissioned
    phased_out = df_agg[df_agg["DateOut"] < baseyear].index
    df_agg.drop(phased_out, inplace=True)

    newer_assets = (df_agg.DateIn > max(grouping_years)).sum()
    if newer_assets:
        logger.warning(
            f"There are {newer_assets} assets with build year "
            f"after last power grouping year {max(grouping_years)}. "
            "These assets are dropped and not considered."
            "Consider to redefine the grouping years to keep them."
        )
        to_drop = df_agg[df_agg.DateIn > max(grouping_years)].index
        df_agg.drop(to_drop, inplace=True)

    df_agg["grouping_year"] = np.take(
        grouping_years, np.digitize(df_agg.DateIn, grouping_years, right=True)
    )

    # calculate (adjusted) remaining lifetime before phase-out (+1 because assuming
    # phase out date at the end of the year)
    df_agg["lifetime"] = df_agg.DateOut - df_agg["grouping_year"] + 1

    df = df_agg.pivot_table(
        index=["grouping_year", "Fueltype", "resource_class"],
        columns="bus",
        values="Capacity",
        aggfunc="sum",
    )

    lifetime = df_agg.pivot_table(
        index=["grouping_year", "Fueltype", "resource_class"],
        columns="bus",
        values="lifetime",
        aggfunc="mean",  # currently taken mean for clustering lifetimes
    )
    # A dictionary that translates carriers into keys for the spatial data structure
    carrier = {
        "OCGT": "gas",
        "CCGT": "gas",
        "coal": "coal",
        "oil": "oil",
        "lignite": "lignite",
        "nuclear": "uranium",
        "solid biomass": "biomass",
        "biogas": "biogas",
    }

    for grouping_year, generator, resource_class in df.index:
        # capacity is the capacity in MW at each node for this
        capacity = df.loc[grouping_year, generator, resource_class]
        capacity = capacity[~capacity.isna()]
        capacity = capacity[capacity > capacity_threshold]
        suffix = "-ac" if generator == "offwind" else ""
        name_suffix = f" {generator}{suffix}-{grouping_year}"
        asset_i = capacity.index + name_suffix
        if generator in ["solar", "onwind", "offwind-ac"]:
            asset_i = capacity.index + " " + resource_class + name_suffix
            name_suffix = " " + resource_class + name_suffix
            cost_key = generator.split("-")[0]
            # to consider electricity grid connection costs or a split between
            # solar utility and rooftop as well, rather take cost assumptions
            # from existing network than from the cost database
            capital_cost = n.generators.loc[
                n.generators.carrier == generator + suffix, "capital_cost"
            ].mean()
            overnight_cost = n.generators.loc[
                n.generators.carrier == generator + suffix, "overnight_cost"
            ].mean()
            marginal_cost = n.generators.loc[
                n.generators.carrier == generator + suffix, "marginal_cost"
            ].mean()
            # check if assets are already in network (e.g. for 2020)
            already_build = n.generators.index.intersection(asset_i)
            new_build = asset_i.difference(n.generators.index)

            # this is for the year 2020
            if not already_build.empty:
                n.generators.loc[already_build, "p_nom"] = n.generators.loc[
                    already_build, "p_nom_min"
                ] = capacity.loc[already_build.str.replace(name_suffix, "")].values
            new_capacity = capacity.loc[new_build.str.replace(name_suffix, "")]

            name_suffix_by = f" {resource_class} {generator}{suffix}-{baseyear}"
            p_max_pu = n.generators_t.p_max_pu[capacity.index + name_suffix_by]

            if not new_build.empty:
                n.add(
                    "Generator",
                    new_capacity.index,
                    suffix=name_suffix,
                    bus=new_capacity.index,
                    carrier=generator,
                    p_nom=new_capacity,
                    marginal_cost=marginal_cost,
                    capital_cost=capital_cost,
                    overnight_cost=overnight_cost,
                    efficiency=costs.at[cost_key, "efficiency"],
                    p_max_pu=p_max_pu.rename(columns=n.generators.bus),
                    build_year=grouping_year,
                    lifetime=costs.at[cost_key, "lifetime"],
                )

        else:
            bus0 = vars(spatial)[carrier[generator]].nodes
            if "EU" not in vars(spatial)[carrier[generator]].locations:
                bus0 = bus0.intersection(capacity.index + " " + carrier[generator])

            # check for missing bus
            missing_bus = pd.Index(bus0).difference(n.buses.index)
            if not missing_bus.empty:
                logger.info(f"add buses {bus0}")
                n.add(
                    "Bus",
                    bus0,
                    carrier=generator,
                    location=vars(spatial)[carrier[generator]].locations,
                    unit="MWh_el",
                )

            already_build = n.links.index.intersection(asset_i)
            new_build = asset_i.difference(n.links.index)
            if (grouping_year, generator) in lifetime.index:
                lifetime_assets = lifetime.loc[
                    grouping_year, generator, resource_class
                ].dropna()
            else:
                lifetime_assets = costs.at[generator, "lifetime"]

            # this is for the year 2020
            if not already_build.empty:
                n.links.loc[already_build, "p_nom_min"] = capacity.loc[
                    already_build.str.replace(name_suffix, "")
                ].values

            if not new_build.empty:
                new_capacity = capacity.loc[new_build.str.replace(name_suffix, "")]

                if generator not in ["solid biomass", "biogas"]:
                    # missing lifetimes are filled with mean lifetime
                    # if mean cannot be built, lifetime is taken from costs.csv
                    if isinstance(lifetime_assets, pd.Series):
                        lifetime_assets = (
                            lifetime_assets.reindex(capacity.index)
                            .fillna(lifetime_assets.mean())
                            .fillna(costs.at[generator, "lifetime"])
                        )

                    n.add(
                        "Link",
                        new_capacity.index,
                        suffix=name_suffix,
                        bus0=bus0,
                        bus1=new_capacity.index,
                        bus2="co2 atmosphere",
                        carrier=generator,
                        marginal_cost=costs.at[generator, "efficiency"]
                        * costs.at[generator, "VOM"],  # NB: VOM is per MWel
                        capital_cost=costs.at[generator, "efficiency"]
                        * costs.at[
                            generator, "capital_cost"
                        ],  # NB: fixed cost is per MWel
                        overnight_cost=costs.at[generator, "efficiency"]
                        * costs.at[
                            generator, "investment"
                        ],  # NB: investment is per MWel
                        p_nom=new_capacity / costs.at[generator, "efficiency"],
                        efficiency=costs.at[generator, "efficiency"],
                        efficiency2=costs.at[carrier[generator], "CO2 intensity"],
                        build_year=grouping_year,
                        lifetime=(
                            lifetime_assets.loc[new_capacity.index]
                            if isinstance(lifetime_assets, pd.Series)
                            else lifetime_assets
                        ),
                    )
                else:
                    if generator == "solid biomass":
                        bus0 = spatial.biomass.df.loc[
                            new_capacity.index, "nodes"
                        ].values
                    elif generator == "biogas":
                        bus0 = spatial.biogas.df.loc[new_capacity.index, "nodes"].values
                    else:
                        logger.error(f"Generator {generator} not recognized.")

                    # We assume the electrical efficiency of a CHP for the biomass and biogas power plants
                    # The EOP from technology data seems to be somewhat too efficient

                    key = "central solid biomass CHP"

                    n.add(
                        "Link",
                        new_capacity.index,
                        suffix=name_suffix,
                        bus0=bus0,
                        bus1=new_capacity.index,
                        carrier=generator,
                        p_nom=new_capacity / costs.at[key, "efficiency"],
                        capital_cost=costs.at[key, "capital_cost"]
                        * costs.at[key, "efficiency"],
                        overnight_cost=costs.at[key, "investment"]
                        * costs.at[key, "efficiency"],
                        marginal_cost=costs.at[key, "VOM"],
                        efficiency=costs.at[key, "efficiency"],
                        build_year=grouping_year,
                        lifetime=lifetime_assets.loc[new_capacity.index],
                    )

        # check if existing capacities are larger than technical potential
        existing_large = n.generators[
            n.generators["p_nom_min"] > n.generators["p_nom_max"]
        ].index
        if len(existing_large):
            logger.warning(
                f"Existing capacities larger than technical potential for {existing_large},\
                           adjust technical potential to existing capacities"
            )
            n.generators.loc[existing_large, "p_nom_max"] = n.generators.loc[
                existing_large, "p_nom_min"
            ]


def add_chp_plants(n, grouping_years, costs, baseyear):
    # rename fuel of CHPs - lignite not in DEA database
    rename_fuel = {
        "Hard Coal": "coal",
        "Coal": "coal",
        "Lignite": "lignite",
        "Natural Gas": "gas",
        "Bioenergy": "urban central solid biomass CHP",
        "Oil": "oil",
    }

    ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)

    if snakemake.input.get("custom_powerplants"):
        if snakemake.input.custom_powerplants.endswith("german_chp_{clusters}.csv"):
            logger.info("Supersedeing default German CHPs with custom_powerplants.")
            ppl = ppl.query("~(Set == 'CHP' and Country == 'DE')")
        ppl = add_custom_powerplants(ppl, snakemake.input.custom_powerplants, True)

    # drop assets which are already phased out / decommissioned
    # drop hydro, waste and oil fueltypes for CHP
    limit = np.max(grouping_years)  # noqa
    drop_fueltypes = ["Hydro", "Other", "Waste", "nicht biogener Abfall"]  # noqa
    chp = ppl.query(
        "Set == 'CHP' and (DateOut >= @baseyear or DateOut != DateOut) and (DateIn <= @limit or DateIn != DateIn) and Fueltype not in @drop_fueltypes"
    ).copy()

    # calculate remaining lifetime before phase-out (+1 because assuming
    # phase out date at the end of the year)
    chp.Fueltype = chp.Fueltype.map(rename_fuel)

    chp["grouping_year"] = np.take(
        grouping_years, np.digitize(chp.DateIn, grouping_years, right=True)
    )
    chp["lifetime"] = (chp.DateOut - chp["grouping_year"] + 1).fillna(
        snakemake.params.costs["fill_values"]["lifetime"]
    )
    chp = chp.loc[
        chp.grouping_year + chp.lifetime > baseyear
    ]  # in add_brownfield this is build_year + lifetime <= baseyear

    # check if the CHPs were read in from MaStR for Germany
    if "Capacity_thermal" in chp.columns:
        if not options["industry"]:
            chp.query("Industry == False", inplace=True)

        thermal_capacity_b = ~chp.Capacity_thermal.isna()
        mastr_chp = chp[thermal_capacity_b]

        # CHPs without thermal capacity are handled later
        chp = chp[~thermal_capacity_b]

        # exclude small CHPs below 500 kW
        mastr_chp = mastr_chp.query("Capacity > 0.5 or Capacity_thermal > 0.5")

        # separate CHPs with substantial power output from those with little power output
        # ratio chosen for reasonable backpressure coefficients c_b
        mastr_chp_power = mastr_chp.query("Capacity > 0.5 * Capacity_thermal").copy()
        mastr_chp_heat = mastr_chp.query("Capacity <= 0.5 * Capacity_thermal").copy()

        mastr_chp_power["p_nom"] = mastr_chp_power.eval("Capacity / Efficiency")
        mastr_chp_power["c_b"] = mastr_chp_power.eval("Capacity / Capacity_thermal")
        mastr_chp_power["c_b"] = mastr_chp_power["c_b"].clip(
            upper=costs.at["CCGT", "c_b"]
        )  # exclude outliers
        mastr_chp_power["efficiency-heat"] = mastr_chp_power.eval("Efficiency / c_b")

        # these CHPs are mainly biomass CHPs
        mastr_chp_heat["efficiency-heat"] = costs.at[
            "central solid biomass CHP", "efficiency-heat"
        ]
        mastr_chp_heat["p_nom"] = (
            mastr_chp_heat.Capacity_thermal / mastr_chp_heat["efficiency-heat"]
        )
        mastr_chp_heat["Efficiency"] = mastr_chp_heat.eval("Capacity / p_nom")
        eff_total_max = costs.loc[
            "central solid biomass CHP", ["efficiency-heat", "efficiency"]
        ].sum()
        eff_heat = mastr_chp_heat["efficiency-heat"]
        mastr_chp_heat["Efficiency"] = mastr_chp_heat["Efficiency"].clip(
            upper=eff_total_max - eff_heat
        )

        mastr_chp = pd.concat([mastr_chp_power, mastr_chp_heat])

        mastr_chp_efficiency_power = mastr_chp.pivot_table(
            index=["grouping_year", "Fueltype"],
            columns="bus",
            values="Efficiency",
            aggfunc=lambda x: np.average(x, weights=mastr_chp.loc[x.index, "p_nom"]),
        )

        mastr_chp_efficiency_heat = mastr_chp.pivot_table(
            index=["grouping_year", "Fueltype"],
            columns="bus",
            values="efficiency-heat",
            aggfunc=lambda x: np.average(x, weights=mastr_chp.loc[x.index, "p_nom"]),
        )

        mastr_chp_p_nom = mastr_chp.pivot_table(
            index=["grouping_year", "Fueltype"],
            columns="bus",
            values="p_nom",
            aggfunc="sum",
        )

        keys = {
            "coal": "central coal CHP",
            "gas": "central gas CHP",
            "waste": "waste CHP",
            "oil": "central gas CHP",
            "lignite": "central coal CHP",
        }
        # add everything as Link
        for grouping_year, generator in mastr_chp_p_nom.index:
            # capacity is the capacity in MW at each node for this
            p_nom = mastr_chp_p_nom.loc[grouping_year, generator].dropna()
            threshold = snakemake.params.existing_capacities["threshold_capacity"]
            p_nom = p_nom[p_nom > threshold]

            efficiency_power = mastr_chp_efficiency_power.loc[grouping_year, generator]
            efficiency_heat = mastr_chp_efficiency_heat.loc[grouping_year, generator]

            for bus in p_nom.index:
                # check if link already exists and set p_nom_min and efficiency
                if generator != "urban central solid biomass CHP":
                    suffix = f" urban central {generator} CHP-{grouping_year}"
                else:
                    suffix = f" {generator}-{grouping_year}"

                if bus + suffix in n.links.index:
                    # only change p_nom_min and efficiency
                    n.links.loc[bus + suffix, "p_nom_min"] = p_nom.loc[bus]
                    n.links.loc[bus + suffix, "p_nom"] = p_nom.loc[bus]
                    n.links.loc[bus + suffix, "efficiency"] = efficiency_power.loc[bus]
                    n.links.loc[bus + suffix, "efficiency2"] = efficiency_heat.loc[bus]
                    continue

                if generator != "urban central solid biomass CHP":
                    # lignite CHPs are not in DEA database - use coal CHP parameters
                    key = keys[generator]
                    if "EU" in vars(spatial)[generator].locations:
                        bus0 = vars(spatial)[generator].nodes[0]
                    else:
                        bus0 = vars(spatial)[generator].df.loc[bus, "nodes"]
                    n.add(
                        "Link",
                        bus,
                        suffix=f" urban central {generator} CHP-{grouping_year}",
                        bus0=bus0,
                        bus1=bus,
                        bus2=bus + " urban central heat",
                        bus3="co2 atmosphere",
                        carrier=f"urban central {generator} CHP",
                        p_nom=p_nom[bus],
                        capital_cost=costs.at[key, "capital_cost"]
                        * costs.at[key, "efficiency"],
                        overnight_cost=costs.at[key, "investment"]
                        * costs.at[key, "efficiency"],
                        marginal_cost=costs.at[key, "VOM"],
                        efficiency=efficiency_power.dropna().loc[bus],
                        efficiency2=efficiency_heat.dropna().loc[bus],
                        efficiency3=costs.at[generator, "CO2 intensity"],
                        build_year=grouping_year,
                        lifetime=costs.at[key, "lifetime"],
                    )
                else:
                    key = "central solid biomass CHP"
                    n.add(
                        "Link",
                        bus,
                        suffix=f" urban {key}-{grouping_year}",
                        bus0=spatial.biomass.df.loc[bus]["nodes"],
                        bus1=bus,
                        bus2=bus + " urban central heat",
                        carrier=generator,
                        p_nom=p_nom[bus],
                        capital_cost=costs.at[key, "capital_cost"]
                        * costs.at[key, "efficiency"],
                        overnight_cost=costs.at[key, "investment"]
                        * costs.at[key, "efficiency"],
                        marginal_cost=costs.at[key, "VOM"],
                        efficiency=efficiency_power.loc[bus],
                        efficiency2=efficiency_heat.loc[bus],
                        build_year=grouping_year,
                        lifetime=costs.at[key, "lifetime"],
                    )

    # CHPs that are not from MaStR
    chp_nodal_p_nom = chp.pivot_table(
        index=["grouping_year", "Fueltype"],
        columns="bus",
        values="Capacity",
        aggfunc="sum",
    )
    for grouping_year, generator in chp_nodal_p_nom.index:
        p_nom = chp_nodal_p_nom.loc[grouping_year, generator].dropna()
        threshold = snakemake.params.existing_capacities["threshold_capacity"]
        p_nom = p_nom[p_nom > threshold]

        for bus in p_nom.index:
            # check if link already exists and set p_nom_min and efficiency
            if generator != "urban central solid biomass CHP":
                suffix = f" urban central {generator} CHP-{grouping_year}"
            else:
                suffix = f" {generator}-{grouping_year}"

            if bus + suffix in n.links.index:
                # only change p_nom_min
                n.links.loc[bus + suffix, "p_nom_min"] = p_nom.loc[bus]
                n.links.loc[bus + suffix, "p_nom"] = p_nom.loc[bus]
                continue

            # CHPs are represented as EOP if no urban central heat bus is available
            if f"{bus} urban central heat" in n.buses.index:
                bus2 = bus + " urban central heat"
            else:
                logger.warning(
                    f"Bus {bus} urban central heat not found. CHP is represented as EOP."
                )
                bus2 = ""

            if generator != "urban central solid biomass CHP":
                # lignite CHPs are not in DEA database - use coal CHP parameters
                key = keys[generator]
                if "EU" in vars(spatial)[generator].locations:
                    bus0 = vars(spatial)[generator].nodes[0]
                else:
                    bus0 = vars(spatial)[generator].df.loc[bus, "nodes"]
                n.add(
                    "Link",
                    bus,
                    suffix=f" urban central {generator} CHP-{grouping_year}",
                    bus0=bus0,
                    bus1=bus,
                    bus2=bus2,
                    bus3="co2 atmosphere",
                    carrier=f"urban central {generator} CHP",
                    p_nom=p_nom[bus] / costs.at[key, "efficiency"],
                    capital_cost=costs.at[key, "capital_cost"]
                    * costs.at[key, "efficiency"],
                    overnight_cost=costs.at[key, "investment"]
                    * costs.at[key, "efficiency"],
                    marginal_cost=costs.at[key, "VOM"],
                    efficiency=costs.at[key, "efficiency"],
                    efficiency2=costs.at[key, "efficiency"] / costs.at[key, "c_b"],
                    efficiency3=costs.at[generator, "CO2 intensity"],
                    build_year=grouping_year,
                    lifetime=costs.at[key, "lifetime"],
                )
            else:
                key = "central solid biomass CHP"
                n.add(
                    "Link",
                    p_nom.index,
                    suffix=f" urban {key}-{grouping_year}",
                    bus0=spatial.biomass.df.loc[p_nom.index]["nodes"],
                    bus1=bus,
                    bus2=bus2,
                    carrier=generator,
                    p_nom=p_nom[bus] / costs.at[key, "efficiency"],
                    capital_cost=costs.at[key, "capital_cost"]
                    * costs.at[key, "efficiency"],
                    overnight_cost=costs.at[key, "investment"]
                    * costs.at[key, "efficiency"],
                    marginal_cost=costs.at[key, "VOM"],
                    efficiency=costs.at[key, "efficiency"],
                    efficiency2=costs.at[key, "efficiency-heat"],
                    build_year=grouping_year,
                    lifetime=costs.at[key, "lifetime"],
                )


def get_efficiency(
    heat_system: HeatSystem,
    carrier: str,
    nodes: pd.Index,
    efficiencies: dict[str, float],
    costs: pd.DataFrame,
) -> pd.Series | float:
    """
    Computes the heating system efficiency based on the sector and carrier
    type.

    Parameters
    ----------
    heat_system : object
    carrier : str
        The type of fuel or energy carrier (e.g., 'gas', 'oil').
    nodes : pandas.Series
        A pandas Series containing node information used to match the heating efficiency data.
    efficiencies : dict
        A dictionary containing efficiency values for different carriers and sectors.
    costs : pandas.DataFrame
        A DataFrame containing boiler cost and efficiency data for different heating systems.

    Returns
    -------
    efficiency : pandas.Series or float
        A pandas Series mapping the efficiencies based on nodes for residential and services sectors, or a single
        efficiency value for other heating systems (e.g., urban central).

    Notes
    -----
    - For residential and services sectors, efficiency is mapped based on the nodes.
    - For other sectors, the default boiler efficiency is retrieved from the `costs` database.
    """

    if heat_system.value == "urban central":
        boiler_costs_name = getattr(heat_system, f"{carrier}_boiler_costs_name")
        efficiency = costs.at[boiler_costs_name, "efficiency"]
    elif heat_system.sector.value == "residential":
        key = f"{carrier} residential space efficiency"
        efficiency = nodes.str[:2].map(efficiencies[key])
    elif heat_system.sector.value == "services":
        key = f"{carrier} services space efficiency"
        efficiency = nodes.str[:2].map(efficiencies[key])
    else:
        raise ValueError(f"Heat system {heat_system} not defined.")

    return efficiency


def add_heating_capacities_installed_before_baseyear(
    n: pypsa.Network,
    costs: pd.DataFrame,
    baseyear: int,
    grouping_years: list[int],
    existing_capacities: pd.DataFrame,
    heat_pump_cop: xr.DataArray,
    heat_pump_source_types: dict[str, list[str]],
    efficiency_file: str,
    use_time_dependent_cop: bool,
    default_lifetime: int,
    energy_totals_year: int,
    capacity_threshold: float,
    use_electricity_distribution_grid: bool,
) -> None:
    """
    Add heating capacities installed before base year.

    Parameters
    ----------
    n : pypsa.Network
        Network to modify
    costs : pd.DataFrame
        Technology costs
    baseyear : int
        Base year for analysis
    grouping_years : list
        Intervals to group capacities
    heat_pump_cop : xr.DataArray
        Heat pump coefficients of performance
    use_time_dependent_cop : bool
        Use time-dependent COPs
    heating_default_lifetime : int
        Default lifetime for heating systems
    existing_capacities : pd.DataFrame
        Existing heating capacity distribution
    heat_pump_source_types : dict
        Heat pump sources by system type
    efficiency_file : str
        Path to heating efficiencies file
    energy_totals_year : int
        Year for energy totals
    capacity_threshold : float
        Minimum capacity threshold
    use_electricity_distribution_grid : bool
        Whether to use electricity distribution grid
    """
    logger.debug(f"Adding heating capacities installed before {baseyear}")

    # Load heating efficiencies
    heating_efficiencies = pd.read_csv(efficiency_file, index_col=[1, 0]).loc[
        energy_totals_year
    ]

    ratios = []
    valid_grouping_years = []

    for heat_system in existing_capacities.columns.get_level_values(0).unique():
        heat_system = HeatSystem(heat_system)

        nodes = pd.Index(
            n.buses.location[n.buses.index.str.contains(f"{heat_system} heat")]
        )

        if (
            not heat_system == HeatSystem.URBAN_CENTRAL
        ) and use_electricity_distribution_grid:
            nodes_elec = nodes + " low voltage"
        else:
            nodes_elec = nodes

            too_large_grouping_years = [
                gy for gy in grouping_years if gy >= int(baseyear)
            ]
            if too_large_grouping_years:
                logger.warning(
                    f"Grouping years >= baseyear are ignored. Dropping {too_large_grouping_years}."
                )
            valid_grouping_years = pd.Series(
                [
                    int(grouping_year)
                    for grouping_year in grouping_years
                    if int(grouping_year) + default_lifetime > int(baseyear)
                    and int(grouping_year) < int(baseyear)
                ]
            )

            assert valid_grouping_years.is_monotonic_increasing

            # get number of years of each interval
            _years = valid_grouping_years.diff()
            # Fill NA from .diff() with value for the first interval
            _years[0] = valid_grouping_years[0] - baseyear + default_lifetime
            # Installation is assumed to be linear for the past
            ratios = _years / _years.sum()

        for ratio, grouping_year in zip(ratios, valid_grouping_years):
            # Add heat pumps
            for heat_source in heat_pump_source_types[heat_system.system_type.value]:
                costs_name = heat_system.heat_pump_costs_name(heat_source)
                efficiency = (
                    heat_pump_cop.sel(
                        heat_system=heat_system.system_type.value,
                        heat_source=heat_source,
                        name=nodes,
                    )
                    .to_pandas()
                    .reindex(index=n.snapshots)
                    if use_time_dependent_cop
                    else costs.at[costs_name, "efficiency"]
                )

                n.add(
                    "Link",
                    nodes,
                    suffix=f" {heat_system} {heat_source} heat pump-{grouping_year}",
                    bus0=nodes_elec,
                    bus1=nodes + " " + heat_system.value + " heat",
                    carrier=f"{heat_system} {heat_source} heat pump",
                    efficiency=efficiency,
                    capital_cost=costs.at[costs_name, "efficiency"]
                    * costs.at[costs_name, "capital_cost"],
                    overnight_cost=costs.at[costs_name, "efficiency"]
                    * costs.at[costs_name, "investment"],
                    p_nom=existing_capacities.loc[
                        nodes, (heat_system.value, f"{heat_source} heat pump")
                    ]
                    * ratio
                    / costs.at[costs_name, "efficiency"],
                    build_year=int(grouping_year),
                    lifetime=costs.at[costs_name, "lifetime"],
                )

            # add resistive heater, gas boilers and oil boilers
            n.add(
                "Link",
                nodes,
                suffix=f" {heat_system} resistive heater-{grouping_year}",
                bus0=nodes_elec,
                bus1=nodes + " " + heat_system.value + " heat",
                carrier=heat_system.value + " resistive heater",
                efficiency=costs.at[
                    heat_system.resistive_heater_costs_name, "efficiency"
                ],
                capital_cost=(
                    costs.at[heat_system.resistive_heater_costs_name, "efficiency"]
                    * costs.at[heat_system.resistive_heater_costs_name, "capital_cost"]
                ),
                overnight_cost=(
                    costs.at[heat_system.resistive_heater_costs_name, "efficiency"]
                    * costs.at[heat_system.resistive_heater_costs_name, "investment"]
                ),
                p_nom=(
                    existing_capacities.loc[
                        nodes, (heat_system.value, "resistive heater")
                    ]
                    * ratio
                    / costs.at[heat_system.resistive_heater_costs_name, "efficiency"]
                ),
                build_year=int(grouping_year),
                lifetime=costs.at[heat_system.resistive_heater_costs_name, "lifetime"],
            )

            efficiency = get_efficiency(
                heat_system, "gas", nodes, heating_efficiencies, costs
            )

            n.add(
                "Link",
                nodes,
                suffix=f" {heat_system} gas boiler-{grouping_year}",
                bus0="EU gas" if "EU gas" in spatial.gas.nodes else nodes + " gas",
                bus1=nodes + " " + heat_system.value + " heat",
                bus2="co2 atmosphere",
                carrier=heat_system.value + " gas boiler",
                efficiency=efficiency,
                efficiency2=costs.at["gas", "CO2 intensity"],
                capital_cost=(
                    costs.at[heat_system.gas_boiler_costs_name, "efficiency"]
                    * costs.at[heat_system.gas_boiler_costs_name, "capital_cost"]
                ),
                overnight_cost=(
                    costs.at[heat_system.gas_boiler_costs_name, "efficiency"]
                    * costs.at[heat_system.gas_boiler_costs_name, "investment"]
                ),
                p_nom=(
                    existing_capacities.loc[nodes, (heat_system.value, "gas boiler")]
                    * ratio
                    / costs.at[heat_system.gas_boiler_costs_name, "efficiency"]
                ),
                build_year=int(grouping_year),
                lifetime=costs.at[heat_system.gas_boiler_costs_name, "lifetime"],
            )

            efficiency = get_efficiency(
                heat_system, "oil", nodes, heating_efficiencies, costs
            )

            n.add(
                "Link",
                nodes,
                suffix=f" {heat_system} oil boiler-{grouping_year}",
                bus0=spatial.oil.nodes,
                bus1=nodes + " " + heat_system.value + " heat",
                bus2="co2 atmosphere",
                carrier=heat_system.value + " oil boiler",
                efficiency=efficiency,
                efficiency2=costs.at["oil", "CO2 intensity"],
                capital_cost=costs.at[heat_system.oil_boiler_costs_name, "efficiency"]
                * costs.at[heat_system.oil_boiler_costs_name, "capital_cost"],
                overnight_cost=costs.at[heat_system.oil_boiler_costs_name, "efficiency"]
                * costs.at[heat_system.oil_boiler_costs_name, "investment"],
                p_nom=(
                    existing_capacities.loc[nodes, (heat_system.value, "oil boiler")]
                    * ratio
                    / costs.at[heat_system.oil_boiler_costs_name, "efficiency"]
                ),
                build_year=int(grouping_year),
                lifetime=costs.at[
                    f"{heat_system.central_or_decentral} gas boiler", "lifetime"
                ],
            )
            # add biomass boilers
            n.add(
                "Link",
                nodes,
                suffix=f" {heat_system} biomass boiler-{grouping_year}",
                bus0=spatial.biomass.df.loc[nodes, "nodes"].values,
                bus1=nodes + " " + heat_system.value + " heat",
                carrier=heat_system.value + " biomass boiler",
                efficiency=costs.at["biomass boiler", "efficiency"],
                capital_cost=costs.at["biomass boiler", "efficiency"]
                * costs.at["biomass boiler", "capital_cost"],
                overnight_cost=costs.at["biomass boiler", "efficiency"]
                * costs.at["biomass boiler", "investment"],
                p_nom=(
                    existing_capacities.loc[
                        nodes, (heat_system.value, "biomass boiler")
                    ]
                    * ratio
                    / costs.at["biomass boiler", "efficiency"]
                ),
                build_year=int(grouping_year),
                lifetime=costs.at["biomass boiler", "lifetime"],
            )

            # delete links with p_nom=nan corresponding to extra nodes in country
            n.remove(
                "Link",
                [
                    index
                    for index in n.links.index.to_list()
                    if str(grouping_year) in index and np.isnan(n.links.p_nom[index])
                ],
            )

            # delete links with capacities below threshold
            n.remove(
                "Link",
                [
                    index
                    for index in n.links.index.to_list()
                    if str(grouping_year) in index
                    and n.links.p_nom[index] < capacity_threshold
                ],
            )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "add_existing_baseyear",
            configfiles=["config/config.nrw.yaml"],
            clusters="adm",
            opts="",
            sector_opts="",
            planning_horizons="2045",
            run="KN2045_Mix",
        )

    configure_logging(snakemake)  # pylint: disable=E0606
    set_scenario_config(snakemake)

    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    options = snakemake.params.sector

    baseyear = snakemake.params.baseyear

    n = pypsa.Network(snakemake.input.network)

    # define spatial resolution of carriers
    spatial = define_spatial(n.buses[n.buses.carrier == "AC"].index, options)
    add_build_year_to_new_assets(n, baseyear)

    Nyears = n.snapshot_weightings.generators.sum() / 8760.0
    costs = load_costs(
        snakemake.input.costs,
        snakemake.params.costs,
        nyears=Nyears,
    )

    grouping_years_power = snakemake.params.existing_capacities["grouping_years_power"]
    grouping_years_heat = snakemake.params.existing_capacities["grouping_years_heat"]
    add_power_capacities_installed_before_baseyear(
        n=n,
        costs=costs,
        grouping_years=grouping_years_power,
        baseyear=baseyear,
        powerplants_file=snakemake.input.powerplants,
        countries=snakemake.config["countries"],
        capacity_threshold=snakemake.params.existing_capacities["threshold_capacity"],
        lifetime_values=snakemake.params.costs["fill_values"],
    )

    if options["heating"]:
        # one could use baseyear here instead (but dangerous if no data)
        fn = snakemake.input.heating_efficiencies
        year = int(snakemake.params["energy_totals_year"])
        heating_efficiencies = pd.read_csv(fn, index_col=[1, 0]).loc[year]

        add_heating_capacities_installed_before_baseyear(
            n=n,
            costs=costs,
            baseyear=baseyear,
            grouping_years=grouping_years_heat,
            heat_pump_cop=xr.open_dataarray(snakemake.input.cop_profiles),
            use_time_dependent_cop=options["time_dep_hp_cop"],
            default_lifetime=snakemake.params.existing_capacities[
                "default_heating_lifetime"
            ],
            existing_capacities=pd.read_csv(
                snakemake.input.existing_heating_distribution,
                header=[0, 1],
                index_col=0,
            ),
            heat_pump_source_types=snakemake.params.heat_pump_sources,
            efficiency_file=snakemake.input.heating_efficiencies,
            energy_totals_year=snakemake.params["energy_totals_year"],
            capacity_threshold=snakemake.params.existing_capacities[
                "threshold_capacity"
            ],
            use_electricity_distribution_grid=options["electricity_distribution_grid"],
        )

    # Set defaults for missing missing values

    if options.get("cluster_heat_buses", False):
        cluster_heat_buses(n)

    n.meta = dict(snakemake.config, **dict(wildcards=dict(snakemake.wildcards)))

    sanitize_custom_columns(n)
    sanitize_carriers(n, snakemake.config)
    n.export_to_netcdf(snakemake.output[0])
