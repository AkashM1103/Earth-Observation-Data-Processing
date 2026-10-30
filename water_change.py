"""Chennai water change from two Sentinel-2 L2A scenes (NDWI + SCL cloud mask).

CLI:
    python water_change.py BEFORE.SAFE AFTER.SAFE [--out outputs] [--threshold 0.0]
Python / API:
    from water_change import analyse
    results = analyse(before_dir, after_dir, out_dir, threshold=0.0)
"""
import argparse, glob, json, os
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds, bounds as win_bounds
from rasterio.enums import Resampling
from scipy import ndimage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

# Chennai city bbox (lon/lat, EPSG:4326) - adjust if needed
CHENNAI_BBOX = (80.10, 12.90, 80.35, 13.25)
BAD_SCL = [0, 1, 3, 8, 9, 10]   # nodata, saturated, shadow, cloud med/high, cirrus
BOA_OFFSET = 1000               # processing baseline >= 04.00 (post Jan 2022)
NODATA = 127


def find(folder, pattern):
    hits = glob.glob(os.path.join(folder, "**", pattern), recursive=True)
    if not hits:
        raise FileNotFoundError(f"{pattern} not found under {folder}")
    return hits[0]


def read_crop(path, bounds_native, ref_shape=None, resampling=Resampling.bilinear):
    with rasterio.open(path) as ds:
        win = from_bounds(*bounds_native, transform=ds.transform).round_offsets().round_lengths()
        shape = ref_shape or (int(win.height), int(win.width))
        arr = ds.read(1, window=win, out_shape=shape, resampling=resampling)
        transform = ds.window_transform(win)
        if ref_shape:
            transform = rasterio.transform.from_bounds(*win_bounds(win, ds.transform), shape[1], shape[0])
        return arr, transform, ds.crs


def load_scene(folder):
    green_p = find(folder, "*_B03_10m.jp2")
    nir_p = find(folder, "*_B08_10m.jp2")
    scl_p = find(folder, "*_SCL_20m.jp2")
    with rasterio.open(green_p) as ds:
        b = transform_bounds("EPSG:4326", ds.crs, *CHENNAI_BBOX)
    green, transform, crs = read_crop(green_p, b)
    shape = green.shape
    nir, _, _ = read_crop(nir_p, b, shape)
    scl, _, _ = read_crop(scl_p, b, shape, Resampling.nearest)  # 20 m -> 10 m
    g = np.clip((green.astype("float32") - BOA_OFFSET) / 10000, 0, None)
    n = np.clip((nir.astype("float32") - BOA_OFFSET) / 10000, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndwi = (g - n) / (g + n)
    invalid = np.isin(scl, BAD_SCL) | ~np.isfinite(ndwi)
    ndwi[invalid] = np.nan
    return ndwi, invalid, transform, crs


def plot_water(ndwi, invalid, title, path, threshold=0.0):
    cat = np.where(invalid, 2, (ndwi > threshold).astype(int))
    cmap = ListedColormap(["#e8dcc0", "#1f78b4", "#999999"])
    plt.figure(figsize=(7, 7))
    plt.imshow(cat, cmap=cmap, vmin=0, vmax=2)
    plt.title(title); plt.axis("off")
    plt.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in ["#e8dcc0", "#1f78b4", "#999999"]],
               labels=["Land", "Water", "Masked (cloud/nodata)"], loc="lower right")
    plt.savefig(path, dpi=200, bbox_inches="tight"); plt.close()


def sea_mask(water, size=31):
    """Sea = wide water body touching the east edge of the crop.
    An opening removes rivers/canals/ponds narrower than ~size pixels,
    so they count as inland water."""
    w = water.astype("uint8")
    core = ndimage.maximum_filter(ndimage.minimum_filter(w, size=size), size=size).astype(bool)
    labels, _ = ndimage.label(core)
    east = np.unique(labels[:, -5:])
    east = east[east != 0]
    return np.isin(labels, east) & water


def analyse(before, after, out="outputs", threshold=0.0):
    """Run the full pipeline, write all outputs to `out`, return the results dict."""
    os.makedirs(out, exist_ok=True)

    nd1, inv1, tr, crs = load_scene(before)
    nd2, inv2, tr2, _ = load_scene(after)
    if nd1.shape != nd2.shape:
        h, w = min(nd1.shape[0], nd2.shape[0]), min(nd1.shape[1], nd2.shape[1])
        nd1, inv1, nd2, inv2 = nd1[:h, :w], inv1[:h, :w], nd2[:h, :w], inv2[:h, :w]

    w1, w2 = nd1 > threshold, nd2 > threshold
    valid = ~(inv1 | inv2)                 # clear in BOTH dates
    w1v, w2v = w1 & valid, w2 & valid      # same mask for both totals
    sea = sea_mask(w1v | w2v)
    change = np.zeros(nd1.shape, dtype="int8")
    change[w2 & ~w1] = 1
    change[w1 & ~w2] = -1
    change[~valid] = NODATA

    px_km2 = abs(tr.a * tr.e) / 1e6

    def km2(m):
        return round(float(m.sum() * px_km2), 2)

    res = {
        "threshold": threshold,
        "clear_both_km2": km2(valid),
        "masked_before_pct": round(float(inv1.mean() * 100), 1),
        "masked_after_pct": round(float(inv2.mean() * 100), 1),
        "total_water_before_km2": km2(w1v),
        "total_water_after_km2": km2(w2v),
        "sea_km2": km2(sea),
        "inland_water_before_km2": km2(w1v & ~sea),
        "inland_water_after_km2": km2(w2v & ~sea),
        "inland_appeared_km2": km2((change == 1) & ~sea),
        "inland_disappeared_km2": km2((change == -1) & ~sea),
    }
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(res, f, indent=2)

    plot_water(nd1, inv1, f"Water - before monsoon (NDWI > {threshold})",
               os.path.join(out, "water_before.png"), threshold)
    plot_water(nd2, inv2, f"Water - after monsoon (NDWI > {threshold})",
               os.path.join(out, "water_after.png"), threshold)

    cmap = ListedColormap(["#d7191c", "#f0f0f0", "#2b83ba", "#999999"])
    vis = np.select([change == -1, change == 0, change == 1], [0, 1, 2], 3)
    plt.figure(figsize=(7, 7)); plt.imshow(vis, cmap=cmap, vmin=0, vmax=3)
    plt.title("Water change (after - before)"); plt.axis("off")
    plt.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in ["#d7191c", "#f0f0f0", "#2b83ba", "#999999"]],
               labels=["Disappeared", "No change", "Appeared", "Masked"], loc="lower right")
    plt.savefig(os.path.join(out, "water_change.png"), dpi=200, bbox_inches="tight"); plt.close()

    with rasterio.open(os.path.join(out, "water_change.tif"), "w", driver="GTiff",
                       height=change.shape[0], width=change.shape[1], count=1,
                       dtype="int8", crs=crs, transform=tr, nodata=NODATA, compress="lzw") as dst:
        dst.write(change, 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before"); ap.add_argument("after")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--threshold", type=float, default=0.0, help="NDWI water threshold")
    a = ap.parse_args()
    print(json.dumps(analyse(a.before, a.after, a.out, a.threshold), indent=2))


if __name__ == "__main__":
    main()
