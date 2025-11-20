import sys
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from matplotlib import patches

# Ensure we can reuse the shared colour palette from the existing Sankey script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from plot_industry_sankey_forecast import COLOR_MAPPING as BASE_COLOR_MAPPING  # type: ignore
except ImportError:  # pragma: no cover - fallback for unexpected import issues
    BASE_COLOR_MAPPING = {}

from plot_industry_sankey_forecast import nice_labels


product_mapper = {
    "Electric arc": "Metallerzeugung ",
    "DRI + Electric arc": "Metallerzeugung ",
    "Integrated steelworks": "Metallerzeugung ",

    "HVC": "Basic chemicals",
    "HVC (mechanical recycling)": "Basic chemicals",
    "HVC (chemical recycling)": "Basic chemicals",
    "Ammonia": "Basic chemicals",
    "Chlorine": "Basic chemicals",
    "Methanol": "Basic chemicals",

    "Other chemicals": "Other chemical industry",
    "Pharmaceutical products etc.": "Other chemical industry",

    "Cement": "Processing of stone and earth (non-metallic mineral processing)",
    "Ceramics & other NMM": "Glass and ceramics",
    "Glass production": "Glass and ceramics",

    "Pulp production": "Paper industry",
    "Paper production": "Paper industry",
    "Printing and media reproduction": "Paper industry",

    "Food, beverages and tobacco": "Food and tobacco",

    "Alumina production": "Non-ferrous metals and foundries",
    "Aluminium - primary production": "Non-ferrous metals and foundries",
    "Aluminium - secondary production": "Non-ferrous metals and foundries",
    "Other non-ferrous metals": "Non-ferrous metals and foundries",

    "Transport equipment": "Vehicle manufacturing (motor vehicles and transport equipment)",
    "Machinery equipment": "Machinery and equipment (mechanical engineering)",

    "Textiles and leather": "Other economic sectors",
    "Wood and wood products": "Other economic sectors",
    "Other industrial sectors": "Other economic sectors",
}


CARRIER_LABELS = {
    "elec": "Electricity",
    "coal": "Coal",
    "coke": "Coal",
    "biomass": "Biomass",
    "methane": "Natural gas",
    "hydrogen": "Hydrogen",
    "heat": "Heat",
    "naphtha": "Naphtha",
    "ammonia": "Ammonia",
    "methanol": "Methanol",
}

EXCLUDED_CARRIERS = {"process emission", "process emission from feedstock"}


def load_production_data(path: Path, country: str) -> pd.Series:
    df = pd.read_csv(path, index_col=0).loc[country]

    return df


def load_ratio_data(path: Path, country: str) -> pd.DataFrame:

    idx = pd.IndexSlice
    df = pd.read_csv(path, header=[0,1], index_col=0)

    df = df.loc[:,idx[country, :]].drop(EXCLUDED_CARRIERS)
    df.columns = df.columns.get_level_values(1)

    df.index = df.index.map(lambda x: CARRIER_LABELS.get(x, x))

    return df


def compute_flows(prod: pd.Series, ratios: pd.DataFrame) -> pd.DataFrame:
    records = []
    for product, kton in prod.items():

        records.append(
            pd.Series(
            ratios.loc[:, product] * kton / 1e3, name=product
        ))

    flows = pd.concat(records, axis=1)

    print(flows)

    flows = flows.T.groupby(product_mapper).sum().T

    return flows


def assign_colors(nodes):
    color_mapping = dict(BASE_COLOR_MAPPING)

    available_cmaps = [plt.cm.tab20, plt.cm.tab20b, plt.cm.tab20c]
    color_list = [mcolors.to_hex(c) for cmap in available_cmaps for c in cmap.colors]

    if len(nodes) > len(color_list):
        additional_needed = len(nodes) - len(color_list)
        hsv_colors = [
            mcolors.hsv_to_rgb((x / additional_needed, 0.7, 0.9)) for x in range(additional_needed)
        ]
        color_list.extend([mcolors.to_hex(c) for c in hsv_colors])

    idx = 0
    for node in nodes:
        if node not in color_mapping:
            color_mapping[node] = color_list[idx % len(color_list)]
            idx += 1

    return color_mapping


def calc_positions(nodes, values):
    positions = {}
    y = 0.0
    total_value = sum(values.get(node, 0) for node in nodes)
    gap = total_value * 0.02 if len(nodes) > 1 else 0.0

    for node in nodes:
        height = values.get(node, 0)
        positions[node] = (y, height)
        y += height + gap
    return positions, y


def draw_nodes(ax, positions, x, align, width, colors):
    for node, (y, h) in positions.items():
        color = colors.get(node, "#cccccc")
        ax.bar(x, h, width=width, bottom=y, align="center", color=color, edgecolor="black", alpha=0.85)

        print_label = nice_labels.get(node, node)

        if align == "right":
            ax.text(x - 0.04, y + h / 2, print_label, ha="right", va="center", fontsize=10)
        else:
            ax.text(x + 0.04, y + h / 2, print_label, ha="left", va="center", fontsize=10)


def draw_links(ax, flows, pos_src, pos_tgt, x_src, x_tgt, width, colors):
    offsets_src = {node: 0.0 for node in pos_src}
    offsets_tgt = {node: 0.0 for node in pos_tgt}

    flows_sorted = flows.sort_values(["source", "target"])

    for _, flow in flows_sorted.iterrows():
        src, tgt, val = flow["source"], flow["target"], flow["value"]
        if src not in pos_src or tgt not in pos_tgt:
            continue

        y_src, _ = pos_src[src]
        y_tgt, _ = pos_tgt[tgt]

        y_s = y_src + offsets_src[src]
        y_t = y_tgt + offsets_tgt[tgt]

        offsets_src[src] += val
        offsets_tgt[tgt] += val

        color = colors.get(src, "#999999")

        p1 = (x_src + width / 2, y_s + val)
        p4 = (x_tgt - width / 2, y_t + val)

        dx = x_tgt - x_src - width
        p2 = (p1[0] + dx / 2, p1[1])
        p3 = (p4[0] - dx / 2, p4[1])

        p5 = (x_tgt - width / 2, y_t)
        p8 = (x_src + width / 2, y_s)
        p6 = (p5[0] - dx / 2, p5[1])
        p7 = (p8[0] + dx / 2, p8[1])

        codes = [
            MplPath.MOVETO,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.LINETO,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CURVE4,
            MplPath.CLOSEPOLY,
        ]
        verts = [p1, p2, p3, p4, p5, p6, p7, p8, p1]
        path = MplPath(verts, codes)
        patch = patches.PathPatch(path, facecolor=color, alpha=0.4, edgecolor=None)
        ax.add_patch(patch)


def add_legend(ax, max_height):
    if max_height <= 0:
        return

    magnitude = 10 ** int(np.log10(max_height) - 0.5) if max_height > 0 else 1
    if max_height / magnitude > 15:
        magnitude *= 5
    elif max_height / magnitude > 8:
        magnitude *= 2

    legend_val = magnitude
    legend_height = legend_val

    ax.set_ylim(-max_height * 0.25, max_height * 1.05)
    legend_x = 0.5
    legend_y = -max_height * 0.2

    rect = patches.Rectangle(
        (legend_x - 0.05, legend_y),
        0.05,
        legend_height,
        facecolor="gray",
        edgecolor="black",
        alpha=0.6,
        clip_on=False,
    )
    ax.add_patch(rect)
    ax.text(
        legend_x + 0.06,
        legend_y + legend_height / 2,
        f"{legend_val:.1f} TWh",
        ha="left",
        va="center",
        fontsize=12,
        fontweight="bold",
        clip_on=False,
    )


def main():
    if len(sys.argv) != 6:
        print(
            "Usage: python plot_industry_product_sankey.py "
            "<production_file> <ratio_file> <country_code> <year> <output_file>"
        )
        sys.exit(1)

    production_file = Path(sys.argv[1])
    ratio_file = Path(sys.argv[2])
    country = sys.argv[3]
    year = sys.argv[4]
    output_file = Path(sys.argv[5])

    production = load_production_data(production_file, country)
    ratios = load_ratio_data(ratio_file, country)
    
    flows = compute_flows(production, ratios)
    flows = flows.stack().reset_index().rename(columns={0: "value", "MWh/tMaterial": "source", "level_1": "target"})

    carriers = sorted(flows["source"].unique())
    products = sorted(flows["target"].unique())

    carrier_values = flows.groupby("source")["value"].sum().to_dict()
    product_values = flows.groupby("target")["value"].sum().to_dict()

    pos_carriers, height_carriers = calc_positions(carriers, carrier_values)
    pos_products, height_products = calc_positions(products, product_values)

    max_height = max(height_carriers, height_products)
    colors = assign_colors(set(carriers) | set(products))

    fig, ax = plt.subplots(figsize=(18, 9))
    width = 0.05
    x_left, x_right = 0, 1

    draw_nodes(ax, pos_carriers, x_left, "right", width, colors)
    draw_nodes(ax, pos_products, x_right, "left", width, colors)
    draw_links(ax, flows, pos_carriers, pos_products, x_left, x_right, width, colors)
    add_legend(ax, max_height)

    ax.set_xlim(x_left - 0.5, x_right + 0.5)
    ax.axis("off")
    ax.set_title(f"PyPSA Industry Energy Flow ({country}, {year})", fontsize=16, pad=20)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(output_file, bbox_inches="tight")
    print(f"Sankey diagram saved to {output_file}")


if __name__ == "__main__":
    main()

