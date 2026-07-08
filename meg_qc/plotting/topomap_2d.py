"""Shared interactive 2D flattened-topomap rendering for MEEGqc reports.

This module centralizes the "classic" flattened topographic map so the subject
report and all dataset reports render the same upright (nose-up), interpolated
view, for MEG (any manufacturer) and EEG montages. Two public entry points:

- ``make_flat_topomap_figure`` — an interpolated scalar field with sensor
  markers, used for the per-channel metric topomaps (STD, PtP, PSD, ECG, EOG).
- ``make_flat_sensor_figure`` — a lobe-coloured sensor scatter (no field), used
  for the 2D sensor-position layout.

Design (mirrors mne.viz.plot_topomap)
-------------------------------------
* **Projection** — azimuthal-equidistant about a sphere-fit vertex axis, so the
  projected radius equals the polar angle (theta) from the vertex. The head
  equator sits at theta = pi/2, which we map to the head-circle radius 1.0. MEG
  helmet sensors reach theta > pi/2 and therefore land *outside* the head
  circle; EEG electrodes stay on/inside it — exactly like MNE.
* **Orientation** — re-oriented from MEEGqc anatomical *lobe* labels (frontal to
  top, occipital to bottom, left/right reflection), which are derived from
  channel-name conventions and so are independent of the acquisition system's
  coordinate frame. Falls back to ``+Y front / +Z up`` when lobes are missing.
* **Interpolation/extrapolation** — Clough-Tocher (cubic) over the sensors plus a
  ring of extra points on the (sensor-encompassing) clip circle whose values are
  the mean of their neighbouring sensors (``border='mean'`` in MNE). This makes
  the field fade smoothly beyond the sensors instead of filling a hard square.
* **Extent controls** — the field is always a disc clipped to ``clip_radius``
  (which encompasses the sensors). Interactive buttons then reveal it
  *outside head* (to clip_radius), *adjusted to head* (to the head circle), or
  *local* (to the sensor convex hull). Sensors can be shown as dots, colour
  coded by value, or hidden.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np
import plotly.graph_objects as go

try:  # SciPy ships with MNE; these imports are expected to succeed.
    from scipy.interpolate import CloughTocher2DInterpolator, griddata
    from scipy.spatial import ConvexHull, Delaunay, cKDTree
except Exception:  # pragma: no cover - defensive only
    CloughTocher2DInterpolator = None
    griddata = None
    ConvexHull = Delaunay = cKDTree = None


_GRID_RES = 170
_HEAD_RADIUS = 1.0           # drawn head circle radius (normalised units)
_EQUATOR_THETA = np.pi / 2.0  # polar angle mapped to the head circle

# Explicit blue(low) -> white -> red(high) scale (RdBu reversed), so the colour
# convention is unambiguous (high = red, low = blue) without relying on
# ``reversescale`` — which the report's control re-application handles unreliably.
BLUE_RED_COLORSCALE = [
    [0.0, "rgb(5,48,97)"], [0.1, "rgb(33,102,172)"], [0.2, "rgb(67,147,195)"],
    [0.3, "rgb(146,197,222)"], [0.4, "rgb(209,229,240)"], [0.5, "rgb(247,247,247)"],
    [0.6, "rgb(253,219,199)"], [0.7, "rgb(244,165,130)"], [0.8, "rgb(214,96,77)"],
    [0.9, "rgb(178,24,43)"], [1.0, "rgb(103,0,31)"],
]


def _smooth_colorscale(name: str, n: int = 32):
    """Return a named colour scale as a smooth explicit ``[[pos, color], ...]``.

    We embed explicit lists (instead of named strings) so colour switching is
    robust regardless of which named scales the report's Plotly bundle knows, and
    we sample ``n`` stops so the scale renders smoothly in the browser (a coarse
    list makes e.g. Turbo look banded / "more rainbow" than the named version).
    """
    try:
        import plotly.colors as _pcolors
        cols = _pcolors.sample_colorscale(name, [i / (n - 1) for i in range(n)])
        return [[i / (n - 1), c] for i, c in enumerate(cols)]
    except Exception:
        try:
            import plotly.colors as _pcolors
            return _pcolors.get_colorscale(name)
        except Exception:
            return None


# Colour-map options offered on every topomap (2D and 3D). Red-Blue (high=red,
# low=blue) is the default; Turbo and Jet are distinct rainbows, Plasma a
# perceptual map. All are smooth, high-resolution explicit scales.
COLORMAP_OPTIONS = [("Red-Blue", BLUE_RED_COLORSCALE)]
for _lab, _name in [("Turbo", "Turbo"), ("Jet", "Jet"), ("Viridis", "Viridis"),
                    ("Plasma", "Plasma"), ("Reds", "Reds")]:
    _cs = _smooth_colorscale(_name)
    if _cs is not None:
        COLORMAP_OPTIONS.append((_lab, _cs))


# ---------------------------------------------------------------------------
# Projection + anatomical orientation
# ---------------------------------------------------------------------------

def _fit_sphere_center(P: np.ndarray) -> np.ndarray:
    """Algebraic least-squares sphere-centre fit for a point cloud."""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    A = np.column_stack([2 * x, 2 * y, 2 * z, np.ones_like(x)])
    b = x ** 2 + y ** 2 + z ** 2
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        return sol[:3]
    except Exception:
        return P.mean(axis=0)


def _orient_2d_by_lobes(X: np.ndarray, Y: np.ndarray, lobes: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Rotate/reflect the flattened plane so frontal=top, right=right.

    Uses MEEGqc lobe labels (frame-independent). No-ops when the labels do not
    provide enough information.
    """
    lobes_l = [str(l).lower() for l in lobes]

    def _centroid(predicate) -> Optional[np.ndarray]:
        idx = [i for i, l in enumerate(lobes_l) if predicate(l)]
        if not idx:
            return None
        return np.array([float(np.mean(X[idx])), float(np.mean(Y[idx]))])

    front = _centroid(lambda l: "frontal" in l)
    occ = _centroid(lambda l: "occipital" in l)
    left = _centroid(lambda l: "left" in l)
    right = _centroid(lambda l: "right" in l)

    up_vec = None
    if front is not None and occ is not None:
        up_vec = front - occ
    elif front is not None:
        up_vec = front
    if up_vec is not None and np.hypot(*up_vec) > 1e-9:
        ang = np.arctan2(up_vec[1], up_vec[0])
        rot = np.pi / 2.0 - ang
        c, s = np.cos(rot), np.sin(rot)
        X, Y = c * X - s * Y, s * X + c * Y
        if left is not None:
            left = np.array([c * left[0] - s * left[1], s * left[0] + c * left[1]])
        if right is not None:
            right = np.array([c * right[0] - s * right[1], s * right[0] + c * right[1]])

    if left is not None and right is not None and right[0] < left[0]:
        X = -X
    return X, Y


def azimuthal_project(
    x: Sequence[float],
    y: Sequence[float],
    z: Optional[Sequence[float]] = None,
    lobes: Optional[Sequence[str]] = None,
) -> Tuple[np.ndarray, np.ndarray, bool]:
    """Flatten 3D sensor positions to 2D (nose up, right on the right).

    Returns ``(x2d, y2d, angular)``. When ``angular`` is True the projected
    radius equals the polar angle from the vertex (so the head equator is at
    pi/2); otherwise a centred orthographic fallback was used (no usable Z).
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)

    def _fallback() -> Tuple[np.ndarray, np.ndarray, bool]:
        X = x - np.nanmean(x)
        Y = y - np.nanmean(y)
        if lobes is not None and len(lobes) == len(X):
            X, Y = _orient_2d_by_lobes(X, Y, lobes)
        return X, Y, False

    if z is None:
        return _fallback()
    z = np.asarray(z, dtype=float).reshape(-1)
    if z.size != x.size:
        return _fallback()

    P = np.column_stack([x, y, z])
    center = _fit_sphere_center(P)
    Pc = P - center
    spread = np.nanstd(Pc, axis=0)
    if spread[2] < 1e-6 * (spread[0] + spread[1] + 1e-12):
        return _fallback()

    up = Pc.mean(axis=0)
    if np.linalg.norm(up) < 1e-9:
        up = np.array([0.0, 0.0, 1.0])
    up = up / np.linalg.norm(up)

    ref = np.array([1.0, 0.0, 0.0]) if abs(up[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = ref - np.dot(ref, up) * up
    e1 = e1 / (np.linalg.norm(e1) + 1e-12)
    e2 = np.cross(up, e1)

    r = np.linalg.norm(Pc, axis=1)
    r_safe = np.where(r > 0, r, 1.0)
    theta = np.arccos(np.clip(np.dot(Pc, up) / r_safe, -1.0, 1.0))
    phi = np.arctan2(np.dot(Pc, e2), np.dot(Pc, e1))
    X = theta * np.cos(phi)
    Y = theta * np.sin(phi)

    if lobes is not None and len(lobes) == len(X):
        X, Y = _orient_2d_by_lobes(X, Y, lobes)
    return X, Y, True


def _scale_to_head(x2d: np.ndarray, y2d: np.ndarray, angular: bool) -> Tuple[np.ndarray, np.ndarray]:
    """Scale projected coords so the head circle has radius ``_HEAD_RADIUS``.

    For angular projections the head equator (theta=pi/2) maps to the head
    circle, so MEG sensors past the equator fall outside it and EEG electrodes
    stay on/inside it. For the orthographic fallback we simply fit the sensors
    just inside the head circle.
    """
    if angular:
        return x2d / _EQUATOR_THETA * _HEAD_RADIUS, y2d / _EQUATOR_THETA * _HEAD_RADIUS
    rad = np.sqrt(x2d ** 2 + y2d ** 2)
    rmax = float(np.nanmax(rad)) if rad.size and np.nanmax(rad) > 0 else 1.0
    scale = 0.9 * _HEAD_RADIUS / rmax
    return x2d * scale, y2d * scale


def _jitter_coincident(x2d: np.ndarray, y2d: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Spread exactly-overlapping markers slightly so all remain visible."""
    xj = x2d.copy()
    yj = y2d.copy()
    key = np.round(np.column_stack([xj, yj]), 6)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    base_r = 0.012 * _HEAD_RADIUS
    for k in range(uniq.shape[0]):
        idx = np.where(inv == k)[0]
        if idx.size <= 1:
            continue
        angles = np.linspace(0.0, 2.0 * np.pi, num=idx.size, endpoint=False)
        xj[idx] += base_r * np.cos(angles)
        yj[idx] += base_r * np.sin(angles)
    return xj, yj


# ---------------------------------------------------------------------------
# Figure furniture
# ---------------------------------------------------------------------------

# Exact head/nose/ear geometry copied from mne.viz.topomap._make_head_outlines
# (normalised to head radius 1.0) so the outline matches MNE's topomaps.
_NOSE_X = np.array([-0.2094, 0.0, 0.2094])
_NOSE_Y = np.array([0.9778, 1.15, 0.9778])
_EAR_X = np.array([0.497, 0.510, 0.518, 0.5299, 0.5419, 0.54, 0.547, 0.532, 0.510, 0.489]) * 2.0
_EAR_Y = np.array([0.0555, 0.0775, 0.0783, 0.0746, 0.0555, -0.0055, -0.0932, -0.1313, -0.1384, -0.1199]) * 2.0


def _head_outline_traces(radius: float = _HEAD_RADIUS, *, visible: bool = True) -> List[go.Scatter]:
    """MNE-style head, nose and ears (exact MNE geometry, detailed ears)."""
    t = np.linspace(0.0, 2.0 * np.pi, 101)
    common = dict(mode="lines", line=dict(color="black", width=1.4), hoverinfo="skip",
                  showlegend=False, visible=visible)
    head = go.Scatter(x=np.cos(t) * radius, y=np.sin(t) * radius, **common)
    nose = go.Scatter(x=_NOSE_X * radius, y=_NOSE_Y * radius, **common)
    right_ear = go.Scatter(x=_EAR_X * radius, y=_EAR_Y * radius, **common)
    left_ear = go.Scatter(x=-_EAR_X * radius, y=_EAR_Y * radius, **common)
    return [head, nose, right_ear, left_ear]


def _eeglab_outline_traces(radius: float = _HEAD_RADIUS, *, visible: bool = True) -> List[go.Scatter]:
    """EEGLAB-style head: clean circle, simple triangular nose, small ear bumps."""
    t = np.linspace(0.0, 2.0 * np.pi, 101)
    common = dict(mode="lines", line=dict(color="black", width=1.4), hoverinfo="skip",
                  showlegend=False, visible=visible)
    head = go.Scatter(x=np.cos(t) * radius, y=np.sin(t) * radius, **common)
    nose = go.Scatter(x=np.array([-0.10, 0.0, 0.10]) * radius,
                      y=np.array([0.995, 1.10, 0.995]) * radius, **common)
    bump = np.linspace(-np.pi / 2.0, np.pi / 2.0, 24)
    right_ear = go.Scatter(x=(1.0 + 0.06 * np.cos(bump)) * radius, y=0.13 * np.sin(bump) * radius, **common)
    left_ear = go.Scatter(x=(-1.0 - 0.06 * np.cos(bump)) * radius, y=0.13 * np.sin(bump) * radius, **common)
    return [head, nose, right_ear, left_ear]


def _ring_mask_trace(inner_x: Sequence[float], inner_y: Sequence[float], *, box_half: float, visible: bool) -> go.Scatter:
    """White 'donut' polygon: fills the box minus the inner ring.

    Used to reveal the field only within the head circle ('adjusted to head') or
    the sensor convex hull ('local'). Relies on the white ``plotly_white`` plot
    background. The fill='toself' hole trick is verified to render in Plotly.
    """
    s = box_half
    outer_x = [-s, s, s, -s, -s]
    outer_y = [-s, -s, s, s, -s]
    ix = list(inner_x) + [inner_x[0]]
    iy = list(inner_y) + [inner_y[0]]
    return go.Scatter(
        x=outer_x + ix, y=outer_y + iy,
        mode="lines", line=dict(width=0, color="white"),
        fill="toself", fillcolor="white",
        hoverinfo="skip", showlegend=False, visible=visible,
    )


def _donut_coords(inner_x, inner_y, box_half: float):
    """Return (xs, ys) of a 'box minus inner ring' polygon for a white mask."""
    s = box_half
    outer_x = [-s, s, s, -s, -s]
    outer_y = [-s, -s, s, s, -s]
    ix = list(inner_x) + [inner_x[0]]
    iy = list(inner_y) + [inner_y[0]]
    return outer_x + ix, outer_y + iy


def _base_topomap_layout(title: str, height: int, view_half: float) -> dict:
    return dict(
        title={"text": title, "x": 0.5, "xanchor": "center", "y": 0.98,
               "yref": "container", "yanchor": "top"},
        template="plotly_white",
        height=height,
        margin=dict(l=30, r=30, t=150, b=24),
        xaxis=dict(visible=False, range=[-view_half, view_half], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-view_half, view_half]),
    )


# ---------------------------------------------------------------------------
# Field interpolation (MNE-style: Clough-Tocher + border-mean ring)
# ---------------------------------------------------------------------------

def _median_sensor_distance(P: np.ndarray) -> float:
    """Median nearest-neighbour distance between sensors."""
    if cKDTree is not None and P.shape[0] >= 2:
        try:
            dd, _ = cKDTree(P).query(P, k=2)
            d = float(np.median(dd[:, 1]))
            if np.isfinite(d) and d > 0:
                return d
        except Exception:
            pass
    span = float(np.linalg.norm(P.max(axis=0) - P.min(axis=0)))
    return max(span / max(P.shape[0], 1), 1e-3)


def _extrapolated_field(
    xs: np.ndarray, ys: np.ndarray, values: np.ndarray, clip_radius: float, grid: np.ndarray
) -> Optional[np.ndarray]:
    """Clough-Tocher field with a border-mean ring (mirrors MNE 'head').

    Returns the field on ``grid`` x ``grid``, clamped to the data range and set
    to NaN outside the ``clip_radius`` disc.
    """
    pts = np.column_stack([xs, ys]).astype(float)
    key = np.round(pts, 6)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    if uniq.shape[0] < 3:
        return None
    P = uniq
    V = np.array([float(np.nanmean(values[inv == k])) for k in range(uniq.shape[0])])
    vmin, vmax = float(np.nanmin(V)), float(np.nanmax(V))

    gx, gy = np.meshgrid(grid, grid)
    outside = (gx ** 2 + gy ** 2) > clip_radius ** 2

    if CloughTocher2DInterpolator is None or Delaunay is None or P.shape[0] < 4:
        if griddata is None:
            return None
        field = griddata((P[:, 0], P[:, 1]), V, (gx, gy), method="linear")
        nanm = ~np.isfinite(field)
        if nanm.any():
            field[nanm] = griddata((P[:, 0], P[:, 1]), V, (gx, gy), method="nearest")[nanm]
        field = np.clip(field, vmin, vmax)
        field[outside] = np.nan
        return field

    # Ring of extra points on the clip circle; values = mean of neighbours.
    dist = _median_sensor_distance(P)
    use_r = clip_radius * 1.1 + dist
    ang = np.arcsin(min(dist / max(clip_radius, 1e-6), 1.0))
    n_pnts = max(16, int(round(2 * np.pi / max(ang, 1e-3))))
    tt = np.linspace(0.0, 2.0 * np.pi, n_pnts, endpoint=False)
    ring = np.column_stack([np.cos(tt) * use_r, np.sin(tt) * use_r])

    all_pos = np.vstack([P, ring])
    try:
        tri = Delaunay(all_pos)
    except Exception:
        return None
    n_real = P.shape[0]
    indices, indptr = tri.vertex_neighbor_vertices
    v_extra = np.zeros(ring.shape[0])
    used = np.zeros(ring.shape[0], bool)
    for k in range(ring.shape[0]):
        gi = n_real + k
        ngb = indptr[indices[gi]: indices[gi + 1]]
        ngb = ngb[ngb < n_real]
        if ngb.size:
            used[k] = True
            v_extra[k] = V[ngb].mean()
    if used.any() and not used.all():
        v_extra[~used] = v_extra[used].mean()
    elif not used.any():
        v_extra[:] = V.mean()

    try:
        interp = CloughTocher2DInterpolator(tri, np.concatenate([V, v_extra]))
        field = interp(gx, gy)
    except Exception:
        return None
    field = np.clip(field, vmin, vmax)
    field[outside] = np.nan
    return field


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def make_flat_topomap_figure(
    x: Sequence[float],
    y: Sequence[float],
    z: Optional[Sequence[float]],
    values: Sequence[float],
    names: Sequence[str],
    *,
    color_title: str,
    title: str,
    hovertext: Optional[Sequence[str]] = None,
    lobes: Optional[Sequence[str]] = None,
    colorscale=BLUE_RED_COLORSCALE,
    reversescale: bool = False,
    height: int = 720,
) -> Optional[go.Figure]:
    """Build an interactive flattened topomap (interpolated field + sensors).

    Three titled control menus:
    - View: Fitted to head (default, field compressed inside the head) /
      Flattened (round) / Flattened (field shape) / Hide field.
    - Colour map: Red-Blue (default, high=red, low=blue) / Turbo / Viridis / Reds.
    - Sensors: Dots (default) / Colour-coded / Hidden.

    Returns ``None`` when there is not enough finite data to render.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    values = np.asarray(values, dtype=float).reshape(-1)
    z_arr = None if z is None else np.asarray(z, dtype=float).reshape(-1)

    n = min(x.size, y.size, values.size, len(names))
    if z_arr is not None:
        n = min(n, z_arr.size)
    if lobes is not None:
        n = min(n, len(lobes))
    if n < 3:
        return None
    x, y, values = x[:n], y[:n], values[:n]
    names = list(names[:n])
    z_arr = z_arr[:n] if z_arr is not None else None
    hov = list(hovertext[:n]) if hovertext is not None else None
    lob = list(lobes[:n]) if lobes is not None else None

    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(values)
    if z_arr is not None:
        finite &= np.isfinite(z_arr)
    if int(np.sum(finite)) < 3:
        return None
    keep = [i for i in range(n) if finite[i]]
    x, y, values = x[finite], y[finite], values[finite]
    names = [names[i] for i in keep]
    hov = [hov[i] for i in keep] if hov is not None else None
    lob = [lob[i] for i in keep] if lob is not None else None
    z_arr = z_arr[finite] if z_arr is not None else None

    x2d, y2d, angular = azimuthal_project(x, y, z_arr, lobes=lob)
    # Natural flattened scaling: the head equator maps to the head circle, so MEG
    # helmet sensors fall *outside* the head and EEG electrodes on/inside it.
    x2d, y2d = _scale_to_head(x2d, y2d, angular)

    max_r = float(np.nanmax(np.sqrt(x2d ** 2 + y2d ** 2))) if x2d.size else _HEAD_RADIUS
    clip_radius = max(_HEAD_RADIUS, max_r) * 1.22  # natural field-extrapolation extent
    # Compression that scales the outermost sensor just inside the head for the
    # "fitted" view (squeeze the whole field within the head — never cut).
    compress = (0.92 * _HEAD_RADIUS) / max(max_r, 1e-6)
    box_half = clip_radius * 1.45

    grid = np.linspace(-clip_radius * 1.02, clip_radius * 1.02, _GRID_RES)
    field = _extrapolated_field(x2d, y2d, values, clip_radius, grid)
    vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
    has_field = field is not None

    xj, yj = _jitter_coincident(x2d, y2d)
    marker_text = hov if hov is not None else names

    # --- Geometry for the three views (positions + mask shape per view). ---
    circ = np.linspace(2.0 * np.pi, 0.0, 160)
    hull_xy = None
    if ConvexHull is not None and x2d.size >= 3:
        try:
            P = np.column_stack([x2d, y2d]); h = ConvexHull(P)
            cx, cy = P[:, 0].mean(), P[:, 1].mean()
            hx = cx + (P[h.vertices, 0] - cx) * 1.06
            hy = cy + (P[h.vertices, 1] - cy) * 1.06
            hull_xy = (hx[::-1], hy[::-1])
        except Exception:
            hull_xy = None
    none_mask = ([], [])
    hull_mask = _donut_coords(hull_xy[0], hull_xy[1], box_half) if hull_xy is not None else none_mask
    head_mask = _donut_coords(np.cos(circ) * _HEAD_RADIUS, np.sin(circ) * _HEAD_RADIUS, box_half)

    grid_nat = list(grid)
    grid_fit = list(grid * compress)
    mx_nat, my_nat = list(xj), list(yj)
    mx_fit, my_fit = list(xj * compress), list(yj * compress)
    view_nat = clip_radius * 1.06
    view_fit = _HEAD_RADIUS * 1.22

    # Default view = "Flattened (round) — field" (field shown + black dots).
    fig = go.Figure()
    if has_field:
        fig.add_trace(go.Contour(
            x=grid_nat, y=grid_nat, z=field, coloraxis="coloraxis",
            connectgaps=False, ncontours=8, contours=dict(coloring="heatmap"),
            line=dict(width=0.5, color="rgba(0,0,0,0.55)"),
            hovertemplate="value=%{z:.3g}<extra></extra>", name="field",
        ))
    else:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", hoverinfo="skip", showlegend=False))

    # ``mode="none"`` (fill only, no line) so the report's global line-thickness
    # control never turns the donut's seam into a visible white line.
    fig.add_trace(go.Scatter(
        x=list(none_mask[0]), y=list(none_mask[1]), mode="none",
        fill="toself", fillcolor="white", hoverinfo="skip", showlegend=False, name="mask",
    ))

    for trace in _head_outline_traces(_HEAD_RADIUS, visible=True):
        fig.add_trace(trace)

    # Two marker traces: black dots (shown with the field) and colour-coded dots.
    fig.add_trace(go.Scatter(
        x=mx_nat, y=my_nat, mode="markers",
        marker=dict(size=3.5, color="black", line=dict(width=0)),
        text=marker_text, hoverinfo="text", showlegend=False, name="sensors-dots", visible=True,
    ))
    fig.add_trace(go.Scatter(
        x=mx_nat, y=my_nat, mode="markers",
        marker=dict(size=9, color=list(values), coloraxis="coloraxis", line=dict(width=0.6, color="#2F3E46")),
        text=marker_text, hoverinfo="text", showlegend=False, name="sensors-colored", visible=False,
    ))

    idx_field, idx_mask = 0, 1
    idx_colored = len(fig.data) - 1
    idx_black = idx_colored - 1

    fig.update_layout(**_base_topomap_layout(title, height, view_nat))
    fig.update_layout(
        showlegend=False,
        coloraxis=dict(
            colorscale=colorscale, reversescale=reversescale, cmin=vmin, cmax=vmax,
            colorbar=dict(title=dict(text=color_title, side="right"), len=0.78, x=0.99),
        ),
    )

    # --- View menu: each option is a full combination of geometry + field/dots. ---
    # field shown  -> black dots; field hidden -> colour-coded dots.
    def _combo(g, mx, my, mask_xy, view, field_on):
        return [
            {"x": [g, list(mask_xy[0]), mx, mx], "y": [g, list(mask_xy[1]), my, my],
             "visible": [field_on, field_on, field_on, (not field_on)]},
            {"xaxis.range": [-view, view], "yaxis.range": [-view, view]},
            [idx_field, idx_mask, idx_black, idx_colored],
        ]
    view_buttons = [
        dict(label="Flattened round (field)", method="update", args=_combo(grid_nat, mx_nat, my_nat, none_mask, view_nat, True)),
        dict(label="Flattened field shape (field)", method="update", args=_combo(grid_nat, mx_nat, my_nat, hull_mask, view_nat, True)),
        dict(label="Fitted to head (field)", method="update", args=_combo(grid_fit, mx_fit, my_fit, head_mask, view_fit, True)),
        # "Flattened round/field-shape, coloured dots" are identical when the field
        # is hidden, so they are merged into one option.
        dict(label="Flattened (coloured dots)", method="update", args=_combo(grid_nat, mx_nat, my_nat, none_mask, view_nat, False)),
        dict(label="Fitted to head (coloured dots)", method="update", args=_combo(grid_fit, mx_fit, my_fit, head_mask, view_fit, False)),
    ]
    colour_buttons = [
        dict(label=lab, method="relayout",
             args=[{"coloraxis.colorscale": cs, "coloraxis.reversescale": False}])
        for lab, cs in COLORMAP_OPTIONS
    ]

    def _dropdown(buttons, name, x):
        # ``name`` becomes the control title in the report's external panel.
        return dict(type="dropdown", name=name, direction="down", x=x, y=1.12, xanchor="left",
                    yanchor="top", showactive=True, bgcolor="#F7FBFF", bordercolor="#2B6CB0",
                    borderwidth=1.0, font=dict(size=11, color="#0F3D6E"),
                    pad=dict(r=2, t=2, l=2, b=2), buttons=buttons)

    if has_field:
        menus = [_dropdown(view_buttons, "View", 0.0), _dropdown(colour_buttons, "Colour map", 0.52)]
    else:
        # No field to interpolate: show colour-coded sensors at fitted positions.
        fig.data[idx_black].visible = False
        fig.data[idx_colored].x = mx_fit
        fig.data[idx_colored].y = my_fit
        fig.data[idx_colored].visible = True
        fig.update_layout(xaxis=dict(range=[-view_fit, view_fit], visible=False, scaleanchor="y"),
                          yaxis=dict(range=[-view_fit, view_fit], visible=False))
        menus = [_dropdown(colour_buttons, "Colour map", 0.0)]
    fig.update_layout(updatemenus=menus)
    return fig


def make_flat_sensor_figure(
    x: Sequence[float],
    y: Sequence[float],
    z: Optional[Sequence[float]],
    names: Sequence[str],
    colors: Sequence[str],
    *,
    title: str,
    lobes: Optional[Sequence[str]] = None,
    height: int = 720,
) -> Optional[go.Figure]:
    """Build a flattened 2D sensor-position layout coloured by lobe."""
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    z_arr = None if z is None else np.asarray(z, dtype=float).reshape(-1)

    n = min(x.size, y.size, len(names), len(colors))
    if z_arr is not None:
        n = min(n, z_arr.size)
    if lobes is not None:
        n = min(n, len(lobes))
    if n < 3:
        return None
    x, y = x[:n], y[:n]
    names = list(names[:n])
    colors = list(colors[:n])
    lobes = list(lobes[:n]) if lobes is not None else None
    z_arr = z_arr[:n] if z_arr is not None else None

    finite = np.isfinite(x) & np.isfinite(y)
    if z_arr is not None:
        finite &= np.isfinite(z_arr)
    if int(np.sum(finite)) < 3:
        return None
    keep = [i for i in range(n) if finite[i]]
    x, y = x[finite], y[finite]
    names = [names[i] for i in keep]
    colors = [colors[i] for i in keep]
    lobes = [lobes[i] for i in keep] if lobes is not None else None
    z_arr = z_arr[finite] if z_arr is not None else None

    x2d, y2d, angular = azimuthal_project(x, y, z_arr, lobes=lobes)
    x2d, y2d = _scale_to_head(x2d, y2d, angular)
    # Compress so every sensor sits inside the head circle for a clean layout.
    rmax = float(np.nanmax(np.sqrt(x2d ** 2 + y2d ** 2))) if x2d.size else 1.0
    if rmax > 0:
        scale = 0.92 * _HEAD_RADIUS / rmax
        x2d, y2d = x2d * scale, y2d * scale
    x2d, y2d = _jitter_coincident(x2d, y2d)

    view_half = _HEAD_RADIUS * 1.16

    fig = go.Figure()
    for trace in _head_outline_traces(_HEAD_RADIUS):
        fig.add_trace(trace)

    group_keys = lobes if lobes is not None else ["channels"] * len(names)
    seen_order: List[str] = []
    for key in group_keys:
        if key not in seen_order:
            seen_order.append(key)
    for key in seen_order:
        idx = [i for i, gk in enumerate(group_keys) if gk == key]
        if not idx:
            continue
        fig.add_trace(go.Scatter(
            x=[x2d[i] for i in idx], y=[y2d[i] for i in idx], mode="markers",
            marker=dict(size=8, color=colors[idx[0]], line=dict(width=0.5, color="#2F3E46")),
            text=[names[i] for i in idx], hoverinfo="text", name=str(key), showlegend=lobes is not None,
        ))

    fig.update_layout(**_base_topomap_layout(title, height, view_half))
    fig.update_layout(
        showlegend=lobes is not None,
        legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5),
    )
    return fig
