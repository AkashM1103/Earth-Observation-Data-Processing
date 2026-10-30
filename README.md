\# Chennai water change (Sentinel-2 L2A, 2025 NE monsoon)



Compares surface water in Chennai before and after the 2025 north-east monsoon using NDWI,

with clouds masked using the Sentinel-2 scene classification layer (SCL).



\## Data (Copernicus Browser, Sentinel-2 L2A, tile T44PMV, relative orbit 119)

| | Before | After |

|---|---|---|

| Scene | S2C\_MSIL2A\_20251006T045711\_N0511\_R119\_T44PMV\_20251006T093213 | S2C\_MSIL2A\_20260114T050151\_N0511\_R119\_T44PMV\_20260114T080009 |

| Date | 2025-10-06 | 2026-01-14 |

| Cloud cover (tile) | 7.46% | 2.07% |



Download both from https://browser.dataspace.copernicus.eu/ and unzip them into `data/before` and `data/after`.



\## Run

```powershell

python -m venv venv

.\\venv\\Scripts\\Activate.ps1

pip install -r requirements.txt

python water\_change.py data\\before\\<BEFORE>.SAFE data\\after\\<AFTER>.SAFE --out outputs

python water\_change.py data\\before\\<BEFORE>.SAFE data\\after\\<AFTER>.SAFE --out outputs\_t01 --threshold 0.1

```



\## Method

1\. Crop B03 (green) and B08 (NIR), 10 m, to the Chennai bounding box (80.10-80.35 E, 12.90-13.25 N).

2\. Resample SCL (20 m) to 10 m (nearest) and mask classes 0, 1, 3, 8, 9, 10 (nodata, saturated, cloud shadow, cloud, cirrus).

3\. Subtract the +1000 BOA offset, then NDWI = (Green - NIR) / (Green + NIR). Water = NDWI > threshold (default 0).

4\. Change map: 1 = water appeared, -1 = disappeared, 0 = unchanged, 127 = masked on either date.

5\. Areas are counted on pixels that are clear on both dates (pixel = 100 m2). The sea is the large water body touching the east edge (morphological opening, 31 px); everything else is inland water.



\## Outputs (`outputs/`)

`water\_before.png`, `water\_after.png`, `water\_change.png`, `water\_change.tif` (int8, EPSG of the scene, nodata 127), `results.json`



\## Results (NDWI > 0)

| | Before | After |

|---|---|---|

| Total water incl. sea (km2) | 299.31 | 292.92 |

| Inland water (km2) | 55.05 | 48.55 |



Inland water appeared on 7.43 km2 and disappeared on 13.93 km2 (clear area compared: 955.67 km2).

With NDWI > 0.1 the inland totals are 41.15 and 37.98 km2 (net change -3.17 km2).



\## Limitations

Bounding-box crop (not the city boundary); fixed NDWI threshold; January clouds mask part of the south-west reservoirs; flooded fields and wet soil near NDWI = 0 add noise; river mouths vary with tide.
   ## API (bonus)
   ```powershell
   pip install -r requirements.txt
   uvicorn api:app --reload
   ```
   Open http://127.0.0.1:8000/docs, or call
   `/analyze?before=2025-10-06&after=2026-01-14[&threshold=0.1]`.
   Scenes are looked up by date in `data/`; results and maps are cached in `api_outputs/`.
