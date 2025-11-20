import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import sys
import numpy as np
import matplotlib.colors as mcolors

from scripts.plot_industry_sankey_forecast import COLOR_MAPPING, nice_labels
from scripts.plot_industry_sankey_pypsa import load_ratio_data, load_production_data, compute_flows


def plot_stacked_bar_comparison(
    data_df,
    color_mapping,
    show_legend=True,
    figsize=(11, 8),
    title='Industrial Energy Input Comparison by Subsector and Year'
    ):
    """
    Create a stacked bar plot comparing energy carriers across subsectors and years.
    
    Parameters:
    -----------
    data_df : pd.DataFrame
        DataFrame with columns: Energy_carrier, Subsector, value, year
    color_mapping : dict
        Dictionary mapping Energy_carrier names to colors
    show_legend : bool
        Whether to display the legend
    figsize : tuple
        Figure size (width, height)
    
    Returns:
    --------
    fig, ax : matplotlib figure and axes objects
    """
    fig, ax = plt.subplots(figsize=figsize)
    
    # Get unique subsectors and years, sorted
    subsectors = sorted(data_df['Subsector'].unique())
    years = sorted(data_df['year'].unique())
    energy_carriers = sorted(data_df['Energy_carrier'].unique())
    
    # Calculate total usage per carrier for 2025 only
    data_2025 = data_df[data_df['year'] == '2025']
    carrier_totals = data_2025.groupby('Energy_carrier')['value'].sum()
    
    # Set up bar positions
    y = np.arange(len(subsectors))
    height = 0.35  # height of each bar
    offsets = {years[0]: -height/2, years[1]: height/2}
    
    # Plot for each year
    for year in years:
        year_data = data_df[data_df['year'] == year]
        
        # Pivot to get energy carriers as columns, subsectors as rows
        pivot_data = year_data.pivot_table(
            index='Subsector',
            columns='Energy_carrier',
            values='value',
            fill_value=0
        )
        
        # Reindex to ensure all subsectors are present
        pivot_data = pivot_data.reindex(subsectors, fill_value=0)
        
        # Plot stacked bars for this year
        left = np.zeros(len(subsectors))
        for carrier in energy_carriers:
            if carrier in pivot_data.columns:
                values = pivot_data[carrier].values
                color = color_mapping.get(carrier, '#cccccc')
                total = carrier_totals.get(carrier, 0)
                ax.barh(
                    y + offsets[year],
                    values,
                    height,
                    left=left,
                    label=f"{carrier} ({total:.1f} TWh)" if year == years[0] else "",
                    color=color,
                    edgecolor='black',
                    linewidth=0.5
                )
                left += values
        
        # Add year labels at the end of each bar (for the middle subsector)
        # This will show which bar corresponds to which year
        middle_idx = len(subsectors) // 2 - 2
        total_width = left[middle_idx]  # Total width for the middle subsector
        ax.text(
            total_width + max(left) * 0.01,  # Slightly to the right of the bar
            y[middle_idx] + offsets[year],  # Position at the middle subsector
            str(year),
            va='center',
            ha='left',
            fontsize=10,
            fontweight='bold',
            color='black'
        )

    # Customize plot
    ax.set_ylabel('Subsector', fontsize=12, fontweight='bold')
    ax.set_xlabel('Energy Demand (TWh)', fontsize=12, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_yticks(y)
    # Apply nice_labels mapping to subsector labels
    subsector_labels = [nice_labels.get(s, s) for s in subsectors]
    ax.set_yticklabels(subsector_labels)

    if show_legend:
        # Calculate grand total for 2025 only
        grand_total = data_2025['value'].sum()
        
        # Create legend with carrier totals
        legend = ax.legend(
            title='Energy Carrier',
            bbox_to_anchor=(.75, 0.95),
            loc='upper left',
            fontsize=9
        )
        
        # Add total line to legend
        from matplotlib.patches import Patch
        handles, labels = ax.get_legend_handles_labels()
        handles.append(Patch(facecolor='none', edgecolor='none'))
        labels.append(f'2025 Total: {grand_total:.1f} TWh')
        
        ax.legend(
            handles=handles,
            labels=labels,
            title='Energy Carrier',
            bbox_to_anchor=(.75, 0.95),
            loc='upper left',
            fontsize=9
        )

    ax.grid(axis='x', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)

    ax.set_xlim(0, 390)

    plt.tight_layout()

    return fig, ax



if __name__ == "__main__":


    years = ['2025', '2045']
    
    data = []
    for year in years:

        forecast_demand_file = snakemake.input.demand_file_forecast
        forecast_demand_df = pd.read_csv(forecast_demand_file)

        usage = forecast_demand_df.groupby(['Energy_carrier', 'Subsector'])[year].sum().reset_index()

        usage.loc[:, 'year'] = year
        usage.rename(columns={year:'value'}, inplace=True)

        data.append(usage)


    # Create the plot
    combined_data = pd.concat(data)

    fig, ax = plot_stacked_bar_comparison(
        combined_data,
        COLOR_MAPPING,
        show_legend=True,
        title='FORECAST Years 2025 and 2045'
        )
    plt.savefig(snakemake.output[0], bbox_inches='tight')
    plt.close()



    data = []
    for year in years:

        pypsa_production_fn = snakemake.input[f'production_file_pypsa_{year}']
        ratios_fn = snakemake.input[f'ratios_file_pypsa_{year}']

        production = load_production_data(pypsa_production_fn, 'DE')
        ratios = load_ratio_data(ratios_fn, 'DE')

        flows = compute_flows(production, ratios)
        flows = flows.stack().reset_index().rename(columns={
            0: "value",
            "MWh/tMaterial": "Energy_carrier",
            "level_1": "Subsector"
            })

        flows.loc[:, 'year'] = year

        data.append(flows)

    combined_data = pd.concat(data)

    fig, ax = plot_stacked_bar_comparison(
        combined_data,
        COLOR_MAPPING,
        show_legend=True,
        title='PYPSA Years 2025 and 2045'
        )
    plt.savefig(snakemake.output[1], bbox_inches='tight')
    plt.close()

    # import sys
    # sys.exit()