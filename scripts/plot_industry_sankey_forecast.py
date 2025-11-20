import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import sys
import numpy as np
import matplotlib.colors as mcolors

# --- Configuration ---
# Define custom colors for nodes here.
# Keys should match the names in the CSV files (Energy_carrier, Application, Subsector).
# If a node is not found here, a color will be automatically assigned.
COLOR_MAPPING = {
    # --- Energy carriers (left column) ---
    "Waste non-RES": "#c97b7b",   # muted reddish waste
    "Other fossil": "#7f7f7f",    # mid grey
    "Other RES": "#66c2a5",       # green-turquoise RES
    "Natural gas": "#9e9e9e",     # warm grey
    "Naphtha": "#984ea3",         # purple (chemical)
    "Hydrogen": "#1abc9c",        # turquoise (chemical)
    "Fuel oil": "#8c564b",        # brown
    "Electricity": "#377eb8",     # blue (electricity theme)
    "District heating": "#e6550d",# district-heat orange
    "Heat": "#e6550d",# district-heat orange
    "Coal": "#4d4d4d",            # dark coal grey
    "Biomass": "#4daf4a",         # green
    "Ambient heat": "#76c7c0",    # teal-ish ambient source

    # --- Uses / demand types (middle column) ---
    # Heat: higher quality -> redder
    "Space heating": "#ffe680",                       # low-T heat (yellow)
    "Space cooling": "#c6dbef",                       # cooling (cool blue)
    "Raw material (feedstock) demand": "#fdd0a2",     # neutral beige
    "Process heat (steam)": "#ffb347",                # mid-grade heat (orange)
    "Process heat (industrial furnaces)": "#d73027",  # high-T heat (red)
    "Process cooling": "#9ecae1",                     # cooler blue
    "Mechanical and other electricity use": "#4a6fdc",# electricity use (blue)
    "Energy balance calibration": "#bdbdbd",          # neutral grey
    "Electrolysis (aluminium smelting)": "#2b8cbe",   # intense electric blue
    "Carbon capture and storage": "#525252",          # dark grey

    # --- Industrial sectors (right column) ---
    "Vehicle manufacturing (motor vehicles and transport equipment)": "#e41a1c",
    "Rubber and plastic products": "#ff7f00",
    "Quarrying of stone and earth; other mining": "#a65628",
    "Processing of stone and earth (non-metallic mineral processing)": "#d9b38c",
    "Paper industry": "#31a354",
    "Other economic sectors": "#969696",
    "Other chemical industry": "#984ea3",             # chemical purple
    "Non-ferrous metals and foundries": "#6baed6",    # steel blue
    "Metallerzeugung ": "#ffd92f",                     # strong yellow metals
    "Machinery and equipment (mechanical engineering)": "#636363",
    "Glass and ceramics": "#fdbf6f",
    "Food and tobacco": "#b15928",
    "Fabricated metal products (metalworking)": "#cab2d6",
    "Basic chemicals": "#a6cee3"                      # light chemical blue
}

nice_labels = {
    "Metallerzeugung ": "Metal production",
}


def main():
    if len(sys.argv) != 5:
        print("Usage: python plot_industry_sankey.py <mapping_file> <demand_file> <year> <output_file>")
        sys.exit(1)

    mapping_file = sys.argv[1]
    demand_file = sys.argv[2]
    year = sys.argv[3]
    output_file = sys.argv[4]

    # Load data
    try:
        mapping_df = pd.read_csv(mapping_file)
        demand_df = pd.read_csv(demand_file)
    except Exception as e:
        print(f"Error loading files: {e}")
        sys.exit(1)

    if year not in demand_df.columns:
        print(f"Year {year} not found in demand file.")
        sys.exit(1)

    # Aggregate flows
    link1 = demand_df.groupby(['Energy_carrier', 'Application'])[year].sum().reset_index()
    link1.columns = ['source', 'target', 'value']
    link1 = link1[link1['value'] > 0]

    link2 = demand_df.groupby(['Application', 'Subsector'])[year].sum().reset_index()
    link2.columns = ['source', 'target', 'value']
    link2 = link2[link2['value'] > 0]

    # Node calculations with Alphabetic Ordering
    l0_nodes = sorted(link1['source'].unique())
    
    # For the middle layer, we need all nodes that appear as target in link1 or source in link2
    l1_nodes = sorted(pd.concat([link1['target'], link2['source']]).unique())
    
    l2_nodes = sorted(link2['target'].unique())
    
    # Assign Colors
    all_nodes = sorted(list(set(l0_nodes) | set(l1_nodes) | set(l2_nodes)))
    
    # Generate default colors for nodes not in COLOR_MAPPING
    # Use a large colormap to ensure distinct colors
    # We'll use tab20 and cycle if needed, or combine multiple maps
    available_cmaps = [plt.cm.tab20, plt.cm.tab20b, plt.cm.tab20c]
    color_list = []
    for cmap in available_cmaps:
        color_list.extend([mcolors.to_hex(c) for c in cmap.colors])
    
    # If we still need more colors, generate them using HSV
    if len(all_nodes) > len(color_list):
        import colorsys
        additional_needed = len(all_nodes) - len(color_list)
        # Generate distinct colors in HSV space
        hsv_colors = [colorsys.hsv_to_rgb(x/additional_needed, 0.7, 0.9) for x in range(additional_needed)]
        color_list.extend([mcolors.to_hex(c) for c in hsv_colors])

    # Assign colors to nodes if not already in COLOR_MAPPING
    color_idx = 0
    for node in all_nodes:
        if node not in COLOR_MAPPING:
            COLOR_MAPPING[node] = color_list[color_idx % len(color_list)]
            color_idx += 1
    
    # Calculate positions
    def calc_y(nodes, values_dict):
        pos = {}
        y = 0
        
        total = sum(values_dict.get(n, 0) for n in nodes)
        gap = total * 0.02 if len(nodes) > 1 else 0
        
        for node in nodes:
            h = values_dict.get(node, 0)
            pos[node] = (y, h)
            y += h + gap
        return pos, y

    # Prepare value dicts for sizing
    # L0: sum of output flows
    l0_vals = link1.groupby('source')['value'].sum().to_dict()
    
    # L1: sum of input flows (or output? usually max of both or average)
    l1_in = link1.groupby('target')['value'].sum()
    l1_out = link2.groupby('source')['value'].sum()
    
    l1_vals = {}
    for node in l1_nodes:
        v_in = l1_in.get(node, 0)
        v_out = l1_out.get(node, 0)
        l1_vals[node] = max(v_in, v_out)

    # L2: sum of input flows
    l2_vals = link2.groupby('target')['value'].sum().to_dict()

    pos0, max_y0 = calc_y(l0_nodes, l0_vals)
    pos1, max_y1 = calc_y(l1_nodes, l1_vals)
    pos2, max_y2 = calc_y(l2_nodes, l2_vals)
    
    max_h = max(max_y0, max_y1, max_y2)
    
    # Wider aspect ratio
    fig, ax = plt.subplots(figsize=(20, 10))
    
    x0, x1, x2 = 0, 1, 2
    width = 0.05
    
    # Draw nodes
    def draw_nodes(pos, x, align):
        for node, (y, h) in pos.items():
            color = COLOR_MAPPING.get(node, '#cccccc')
            print_label = nice_labels.get(node, node)

            ax.bar(x, h, width=width, bottom=y, align='center', color=color, edgecolor='black', alpha=0.8)
            
            # Text placement
            if align == 'right':
                ax.text(x - 0.04, y + h/2, print_label, ha='right', va='center', fontsize=10)
            elif align == 'center':
                ax.text(x, y + h/2, print_label, ha='center', va='center', fontsize=10, rotation=0, 
                        bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
            elif align == 'left':
                ax.text(x + 0.04, y + h/2, print_label, ha='left', va='center', fontsize=10)

    draw_nodes(pos0, x0, 'right')
    draw_nodes(pos1, x1, 'center')
    draw_nodes(pos2, x2, 'left')

    # Draw curved flows
    def draw_links(links, pos_src, pos_tgt, x_src, x_tgt, width, color_by='source'):
        y_offsets_src = {n: 0.0 for n in pos_src}
        y_offsets_tgt = {n: 0.0 for n in pos_tgt}
        
        # Sort links to minimize crossing? Or just iterate.
        # Sorting by source then target helps visual order
        links_sorted = links.sort_values(['source', 'target'])
        
        for _, row in links_sorted.iterrows():
            src, tgt, val = row['source'], row['target'], row['value']
            if src not in pos_src or tgt not in pos_tgt: continue
            
            y_src, h_src = pos_src[src]
            y_tgt, h_tgt = pos_tgt[tgt]
            
            y_s = y_src + y_offsets_src[src]
            y_t = y_tgt + y_offsets_tgt[tgt]
            
            y_offsets_src[src] += val
            y_offsets_tgt[tgt] += val
            
            # Color logic
            if color_by == 'source':
                color = COLOR_MAPPING.get(src, '#999999')
            else:
                color = COLOR_MAPPING.get(tgt, '#999999')
            
            # Bezier curve
            p1 = (x_src + width/2, y_s + val)
            p4 = (x_tgt - width/2, y_t + val)
            
            dx = x_tgt - x_src - width
            p2 = (p1[0] + dx/2, p1[1])
            p3 = (p4[0] - dx/2, p4[1])
            
            p5 = (x_tgt - width/2, y_t)
            p8 = (x_src + width/2, y_s)
            p6 = (p5[0] - dx/2, p5[1])
            p7 = (p8[0] + dx/2, p8[1])
            
            codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
                     Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CLOSEPOLY]
            
            verts = [p1, p2, p3, p4, p5, p6, p7, p8, p1]
            
            path = Path(verts, codes)
            patch = patches.PathPatch(path, facecolor=color, alpha=0.4, edgecolor=None)
            ax.add_patch(patch)

    # Link 1: Left -> Middle. Color by Left (source)
    draw_links(link1, pos0, pos1, x0, x1, width, color_by='source')
    
    # Link 2: Middle -> Right. Color by Right (target)
    draw_links(link2, pos1, pos2, x1, x2, width, color_by='target')

    # Legend for Flow Width (Energy in TWh)
    # Determine a nice round number for the legend
    magnitude = 10 ** int(np.log10(max_h) - 0.5)
    if magnitude == 0: magnitude = 1
    
    # Adjust magnitude to be 1, 2, or 5 * 10^k
    base = magnitude
    if max_h / base > 15: magnitude *= 5
    elif max_h / base > 8: magnitude *= 2
    
    legend_val = magnitude
    legend_height = legend_val
    
    # Draw the legend patch
    # Position: Bottom center, below the graph
    # We need to adjust plot limits to make room or use fig coordinates
    
    # Add some padding at the bottom for the legend
    ax.set_ylim(-max_h * 0.25, max_h * 1.05)
    
    legend_x = 1.0 # Center of middle column
    legend_y = -max_h * 0.2
    
    # Draw a rectangle representing the legend value
    rect = patches.Rectangle((legend_x - 0.05, legend_y), 0.05, legend_height, 
                             facecolor='gray', edgecolor='black', alpha=0.6, clip_on=False)
    ax.add_patch(rect)
    
    ax.text(legend_x + 0.06, legend_y + legend_height/2, f" {legend_val} TWh", 
            ha='left', va='center', fontsize=12, fontweight='bold', clip_on=False)

    ax.set_xlim(x0 - 0.5, x2 + 0.5)
    ax.axis('off')
    ax.set_title(f"FORECAST Industry Energy Flow {year}", fontsize=16, pad=20)
    
    plt.tight_layout()
    plt.savefig(output_file, bbox_inches='tight')
    print(f"Sankey diagram saved to {output_file}")

if __name__ == "__main__":
    main()
