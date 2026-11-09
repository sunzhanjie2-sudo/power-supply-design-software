"""Draw the field and conductor boundaries from the same Elmer tetrahedra."""
import os
from pathlib import Path

from .storage import app_home, write
from .presentation import winding_colors

os.environ.setdefault('MPLCONFIGDIR', str(app_home() / 'data/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LogNorm, Normalize, TwoSlopeNorm, to_rgb
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

_font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
FONT = FontProperties(fname=str(_font)) if _font.exists() else FontProperties()
INK, MUTED = '#183448', '#526879'
PLANE_TOL_M = 1e-13
EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def boundary(tet):
    faces = np.concatenate([tet[:, order] for order in ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))])
    _, index, count = np.unique(np.sort(faces, axis=1), axis=0, return_index=True, return_counts=True)
    return faces[index[count == 1]]


def slice_elements(field):
    """One XZ polygon per cut cell. At a shared planar face prefer the +Y cell."""
    xyz = field['points'][field['tetra']]
    y = xyz[:, :, 1]
    selected = np.flatnonzero((y.min(axis=1) <= PLANE_TOL_M) & (y.max(axis=1) >= -PLANE_TOL_M))
    selected = selected[np.argsort(-y[selected].mean(axis=1), kind='stable')]
    polygons, indices, seen = [], [], set()
    for index in selected:
        cell = xyz[index]
        distance = np.where(np.abs(cell[:, 1]) <= PLANE_TOL_M, 0, cell[:, 1])
        vertices = list(cell[distance == 0][:, [0, 2]])
        for a, b in EDGES:
            if distance[a] * distance[b] < 0:
                t = distance[a] / (distance[a] - distance[b])
                vertices.append((cell[a] + t * (cell[b] - cell[a]))[[0, 2]])
        if len(vertices) < 3:
            continue
        xy = np.unique(np.round(vertices, 13), axis=0)
        if len(xy) < 3:
            continue
        key = xy.tobytes()
        if key in seen:
            continue
        seen.add(key)
        offset = xy - xy.mean(axis=0)
        order = np.argsort(np.arctan2(offset[:, 1], offset[:, 0]))
        polygons.append(xy[order] * 1000)
        indices.append(index)
    return polygons, np.asarray(indices, dtype=int)


def region_perimeter(polygons):
    """Cancel internal edges (including coplanar mesh faces), keeping only interfaces."""
    if not polygons:
        return np.empty((0, 2, 2))
    edges = np.round(np.concatenate([np.stack((p, np.roll(p, -1, axis=0)), axis=1)
                                     for p in polygons]), 9)
    a, b = edges[:, 0], edges[:, 1]
    swap = (a[:, 0] > b[:, 0]) | ((a[:, 0] == b[:, 0]) & (a[:, 1] > b[:, 1]))
    edges[swap] = edges[swap, ::-1]
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    return edges[counts == 1]


def closed_profiles(edges):
    """Return centers of closed, connected outlines (used for labels and audit)."""
    links = {}
    for a, b in edges:
        a, b = tuple(a), tuple(b)
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)
    remaining, centers = set(links), []
    while remaining:
        first = remaining.pop()
        component, pending = [first], [first]
        while pending:
            node = pending.pop()
            for neighbor in links[node]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.append(neighbor)
                    pending.append(neighbor)
        if all(len(links[node]) == 2 for node in component):
            pts = np.asarray(component)
            centers.append((pts.min(axis=0) + pts.max(axis=0)) / 2)
    return centers


def title(ax, value):
    ax.set_title(value, loc='left', fontproperties=FONT, fontsize=13, color=INK, pad=11)


def winding_legend(fig, colors, core=False):
    handles = [Line2D([], [], color=colors[wid], lw=4, label=wid) for wid in colors]
    if core:
        handles.append(Line2D([], [], color='#8f9fa9', lw=4, label='磁芯'))
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5, .002), ncol=min(9, len(handles)),
               frameon=False, prop=FONT, handlelength=1.5, columnspacing=1.8)


def field_plot(out, field, g, primary, polygons, indices, perimeters, profiles, colors):
    ids = field['regions'][indices]
    sections = g['physical_sections']
    magnitude = np.linalg.norm(field['B'][indices], axis=1) * 1000
    upper = max(float(magnitude.max()), 0.011)
    lower = min(0.01, upper / 10)
    norm = LogNorm(vmin=lower, vmax=upper)
    material = np.concatenate([p for p, body in zip(polygons, ids) if body != 1])
    window = np.concatenate([p for p, body in zip(polygons, ids) if body >= 3 and p[:, 0].mean() > 0])
    def padded(points, factor, minimum):
        low, high = points.min(axis=0), points.max(axis=0)
        pad = np.maximum((high - low) * factor, minimum)
        return low - pad, high + pad
    low, high = padded(material, .075, .1)
    zlow, zhigh = padded(window, .14, .12)
    fig = plt.figure(figsize=(10.6, 5.55), facecolor='white')
    grid = fig.add_gridspec(1, 3, width_ratios=(1.15, .60, .045),
                            left=.075, right=.91, bottom=.17, top=.89, wspace=.34)
    full, zoom, color_axis = [fig.add_subplot(grid[0, i]) for i in range(3)]
    for ax, (a, b) in ((full, (low, high)), (zoom, (zlow, zhigh))):
        image = PolyCollection(polygons, array=np.maximum(magnitude, lower), cmap='cividis',
                               norm=norm, edgecolors='none', antialiaseds=False, zorder=1)
        ax.add_collection(image)
        ax.set(xlim=(a[0], b[0]), ylim=(a[1], b[1]), aspect='equal', xlabel='x (mm)', ylabel='z (mm)')
        ax.tick_params(labelsize=8, colors=MUTED, length=3)
        ax.xaxis.label.set_color(MUTED); ax.yaxis.label.set_color(MUTED)
        for spine in ax.spines.values():
            spine.set_color('#acb8bf')
        ax.add_collection(LineCollection(perimeters[2], colors='#f3f6f6', linewidths=.85, zorder=3))
        for i, section in enumerate(sections, 3):
            line = perimeters[i]
            dark, bright = (2.0, 1.05) if ax is full else (3.25, 1.8)
            for color, width in (('#152332', dark), (colors[section['winding_id']], bright)):
                ax.add_collection(LineCollection(line, colors=color, linewidths=width,
                                                capstyle='round', zorder=5))
    centers = np.asarray([p.mean(axis=0) for p in polygons])
    vectors = field['B'][indices][:, [0, 2]]
    sel = np.unique([np.square(centers - [x, z]).sum(axis=1).argmin()
                     for x in np.linspace(low[0], high[0], 16) for z in np.linspace(low[1], high[1], 16)])
    sel = sel[(ids[sel] <= 2) & (np.linalg.norm(vectors[sel], axis=1) > 1e-9)]
    if len(sel):
        v = vectors[sel] / np.linalg.norm(vectors[sel], axis=1)[:, None] * max(high-low) / 42
        full.quiver(*centers[sel].T, *v.T, angles='xy', scale_units='xy', scale=1,
                    color='#f7f8ef', width=.0032, alpha=.85, zorder=2.5)
    full.add_patch(Rectangle(zlow, *(zhigh - zlow), fill=False, edgecolor='white', lw=1.1,
                             linestyle=(0, (4, 3)), zorder=6))
    # Label the actual section cuts. For densely segmented designs use one label
    # per port and retain the complete section list in the report.
    labels = {}
    for region, section in enumerate(sections, 3):
        key = section['section_id'] if len(sections) <= 8 else section['winding_id']
        entry = labels.setdefault(key, (section['winding_id'], []))
        entry[1].extend(p for p in profiles[region] if p[0] > 0)
    available = [(key, wid, pts) for key, (wid, pts) in labels.items() if pts]
    offsets = np.linspace(.83, .17, len(available)) if len(available)>1 else [.5]
    for (label, wid, pts), height in zip(available, offsets):
        z = zlow[1] + height*(zhigh[1]-zlow[1])
        point = min(pts, key=lambda p: abs(p[1]-z))
        zoom.annotate(label if len(label)<=13 else label[:11]+'…', xy=point,
                      xytext=(1.09, height), textcoords='axes fraction', color=INK,
                      fontsize=8, fontproperties=FONT, va='center', annotation_clip=False,
                      arrowprops=dict(arrowstyle='-', color=colors[wid], linewidth=.9,
                                      shrinkA=2, shrinkB=4), zorder=8)
    title(full, f'磁场总览   {primary} = 1 A')
    title(zoom, '右侧绕线窗口放大')
    bar = fig.colorbar(image, cax=color_axis, extend='min' if magnitude.min() < lower else 'neither')
    ticks = [10.0**i for i in range(-8, 9) if lower <= 10.0**i <= upper]
    bar.set_ticks(ticks, labels=[f'{v:g}' for v in ticks])
    bar.ax.set_title('|B|\nmT', fontsize=10, color=INK, pad=6)
    bar.ax.tick_params(labelsize=8, width=.5)
    winding_legend(fig, colors)
    fig.savefig(out / 'model_field.png', dpi=164, facecolor='white')
    plt.close(fig)


def shaded_faces(points, base):
    normals = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-30)
    lighting = .78 + .22 * (normals @ np.array([-.38, -.55, .74]))
    return np.clip(np.asarray(to_rgb(base))[None, :] * lighting[:, None], 0, 1)


def winding_model(out, field, g, polygons, indices, colors):
    # Full assembly at left. At right draw the actual rear semicircles and their cut faces.
    points, tet, ids = field['points']*1000, field['tetra'], field['regions']
    fig = plt.figure(figsize=(10.6, 4.9), facecolor='white')
    axes = [fig.add_subplot(1, 2, i+1, projection='3d') for i in range(2)]
    fig.subplots_adjust(left=.025, right=.975, top=.91, bottom=.08, wspace=.06)
    core = points[boundary(tet[ids == 2])]
    axes[0].add_collection3d(Poly3DCollection(core, facecolors='#8395a1', alpha=.13, linewidths=0))
    full, half, full_colors, half_colors = [], [], [], []
    for region, section in enumerate(g['physical_sections'], 3):
        triangles = points[boundary(tet[ids == region])]
        color = colors[section['winding_id']]
        face_colors = shaded_faces(triangles, color)
        full.extend(triangles); full_colors.extend(face_colors)
        # The model meshes each closed turn in four azimuth sectors including y=0.
        keep = triangles[:, :, 1].min(axis=1) >= -1e-7
        half.extend(triangles[keep]); half_colors.extend(face_colors[keep])
        for i in np.flatnonzero(ids[indices] == region):
            p = polygons[i]
            half.append(np.column_stack((p[:, 0], np.zeros(len(p)), p[:, 1])))
            half_colors.append(to_rgb(color))
    for ax, faces, facecolors in zip(axes, [full, half], [full_colors, half_colors]):
        ax.add_collection3d(Poly3DCollection(faces, facecolors=facecolors, linewidths=0, antialiaseds=False))
        ax.set_proj_type('ortho'); ax.set_axis_off()
    full_pts = points[np.unique(tet[ids != 1])]
    half_pts = points[np.unique(tet[ids >= 3])]
    for ax, pts in zip(axes, [full_pts, half_pts[half_pts[:, 1] >= -1e-7]]):
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        pad = max(hi-lo)*.035
        ax.set(xlim=(lo[0]-pad, hi[0]+pad), ylim=(lo[1]-pad, hi[1]+pad), zlim=(lo[2]-pad, hi[2]+pad))
        ax.set_box_aspect(hi-lo+2*pad, zoom=1.05)
    axes[0].view_init(23, -59); axes[1].view_init(24, -70)
    title(axes[0], '完整装配 · 透明磁芯'); title(axes[1], '绕组剖视 · 移去前半圈与磁芯')
    winding_legend(fig, colors, core=True)
    fig.savefig(out / 'winding_model.png', dpi=146)
    plt.close(fig)


def matrix_plot(out, report):
    k = np.asarray(report['k_ports'])
    signed = np.min(k) < 0
    if signed:
        norm, cmap = TwoSlopeNorm(vcenter=0, vmin=-1, vmax=1), plt.get_cmap('RdBu')
    else:
        norm, cmap = Normalize(vmin=min(.99, float(k.min())), vmax=max(1, float(k.max()))), plt.get_cmap('Blues')
    n = len(k)
    fig, ax = plt.subplots(figsize=(max(5.6, n*.88), max(4, n*.72)), layout='constrained')
    picture = ax.imshow(k, norm=norm, cmap=cmap)
    ax.set_xticks(range(n), report['port_order'], fontproperties=FONT, rotation=25 if n>5 else 0)
    ax.set_yticks(range(n), report['port_order'], fontproperties=FONT)
    for i in range(n):
        for j in range(n):
            rgb = cmap(norm(k[i, j]))[:3]
            light = np.dot(rgb, [.2126, .7152, .0722])
            ax.text(j, i, f'{k[i,j]:.5f}', ha='center', va='center', fontsize=max(8, 13-n//2),
                    color='white' if light<.48 else INK)
    title(ax, '端口间有符号耦合系数')
    fig.colorbar(picture, ax=ax, shrink=.78)
    fig.savefig(out/'k_matrix.png', dpi=135)
    plt.close(fig)


def plots(out, report, field, geometry):
    colors = winding_colors(geometry)
    polygons, indices = slice_elements(field)
    ids = field['regions'][indices]
    perimeters, profiles, counts = {}, {}, []
    for region in range(2, 3 + len(geometry['physical_sections'])):
        perimeters[region] = region_perimeter([polygons[i] for i in np.flatnonzero(ids == region)])
        if region >= 3:
            section = geometry['physical_sections'][region-3]
            profiles[region] = closed_profiles(perimeters[region])
            counts.append(dict(section=section['section_id'], winding=section['winding_id'],
                               positive_x=sum(int(p[0]>0) for p in profiles[region]),
                               negative_x=sum(int(p[0]<0) for p in profiles[region]),
                               perimeter_segments=len(perimeters[region])))
    with plt.rc_context({'text.parse_math': False, 'axes.unicode_minus': False}):
        field_plot(out, field, geometry, report['primary_port'], polygons, indices, perimeters, profiles, colors)
        winding_model(out, field, geometry, polygons, indices, colors)
        matrix_plot(out, report)
    core_b = np.linalg.norm(field['B'][field['regions']==2], axis=1)
    write(out/'field-summary.json', dict(primary_unit_current_A=1, excitation_port=report['primary_port'],
          max_core_B_T=float(core_b.max()), section_plane='y=0 m', slice_field_unit='mT',
          perimeter_source='exterior edges of sliced Elmer conductor cells', winding_sections=counts,
          note='Normalized linear unit-current field; conductor outlines keep the underlying elemental field visible.'))

