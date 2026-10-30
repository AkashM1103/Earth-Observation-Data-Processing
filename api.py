"""FastAPI wrapper around water_change.analyse().

Run:   uvicorn api:app --reload
Docs:  http://127.0.0.1:8000/docs

Scenes are looked up by acquisition date inside DATA_DIR (default: data/),
e.g. data/before/S2C_MSIL2A_20251006T...SAFE  ->  date 2025-10-06.
"""
import datetime as dt
import glob, json, os, re, threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from water_change import analyse

DATA_DIR = os.environ.get("DATA_DIR", "data")
OUT_DIR = os.environ.get("OUT_DIR", "api_outputs")
DEFAULT_TILE = os.environ.get("DEFAULT_TILE", "T44PMV")
FILES = {"water_before.png", "water_after.png", "water_change.png",
         "water_change.tif", "results.json"}

app = FastAPI(title="Chennai water change API",
              description="NDWI water change between two Sentinel-2 L2A dates.")
lock = threading.Lock()   # matplotlib is not thread-safe; run one analysis at a time


def list_scenes():
    """Return {(date, tile): path} for every L2A .SAFE folder under DATA_DIR."""
    scenes = {}
    for p in glob.glob(os.path.join(DATA_DIR, "**", "*_MSIL2A_*.SAFE"), recursive=True):
        m = re.search(r"_MSIL2A_(\d{8})T.*_(T\d{2}[A-Z]{3})_", os.path.basename(p))
        if m:
            d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
            scenes[(d, m.group(2))] = p
    return scenes


def scene_for(date, tile, scenes):
    path = scenes.get((date, tile))
    if path is None:
        have = sorted(f"{d} ({t})" for d, t in scenes)
        raise HTTPException(404, detail={"error": f"No scene for {date} tile {tile} in '{DATA_DIR}'",
                                         "available": have})
    return path


@app.get("/")
def root():
    return {"service": "Chennai water change API", "docs": "/docs",
            "try": "/analyze?before=2025-10-06&after=2026-01-14"}


@app.get("/scenes")
def scenes():
    """List the scenes (dates and tiles) that are available locally."""
    return [{"date": str(d), "tile": t, "folder": p} for (d, t), p in sorted(list_scenes().items())]


@app.get("/analyze")
def analyze(before: dt.date = Query(..., description="Date of the earlier scene, YYYY-MM-DD"),
            after: dt.date = Query(..., description="Date of the later scene, YYYY-MM-DD"),
            threshold: float = Query(0.0, ge=-1.0, le=1.0, description="NDWI water threshold"),
            tile: str = Query(DEFAULT_TILE, description="Sentinel-2 tile code")):
    """Compare water between two dates. Returns areas in sq km and links to the maps and GeoTIFF."""
    if before >= after:
        raise HTTPException(400, "'before' must be earlier than 'after'")
    avail = list_scenes()
    b_path, a_path = scene_for(before, tile, avail), scene_for(after, tile, avail)

    run_id = f"{before}_{after}_{tile}_t{threshold}"
    out = os.path.join(OUT_DIR, run_id)
    res_file = os.path.join(out, "results.json")
    with lock:
        cached = os.path.exists(res_file)
        if cached:
            with open(res_file) as f:
                results = json.load(f)
        else:
            results = analyse(b_path, a_path, out, threshold)
    return {"before": str(before), "after": str(after), "tile": tile, "cached": cached,
            "results": results,
            "files": {name: f"/files/{run_id}/{name}" for name in sorted(FILES)}}


@app.get("/files/{run_id}/{filename}")
def get_file(run_id: str, filename: str):
    """Download a map (PNG), the change GeoTIFF or results.json from a finished run."""
    if filename not in FILES or not re.fullmatch(r"[\w.\-]+", run_id):
        raise HTTPException(404, "File not found")
    path = os.path.join(OUT_DIR, run_id, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Run not found - call /analyze first")
    return FileResponse(path)
