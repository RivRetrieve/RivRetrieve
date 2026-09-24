"""generate_station_map : CatalogueStationParquetFiles -> StandaloneLeafletMapHTML.

Generates an interactive Leaflet + MarkerCluster map with 78,000+ stations,
provider toggles, station search, and copyable RivRetrieve code snippets.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import polars as pl

PROVIDER_METADATA = {
    "usgs_nwis": {"name": "USGS NWIS", "country": "United States", "color": "#1f77b4"},
    "br_ana": {"name": "ANA", "country": "Brazil", "color": "#2ca02c"},
    "ca_eccc": {"name": "ECCC", "country": "Canada", "color": "#d62728"},
    "fr_hubeau": {"name": "Hub'Eau", "country": "France", "color": "#9467bd"},
    "fr_hydroportail": {"name": "HydroPortail", "country": "France", "color": "#8c564b"},
    "no_nve": {"name": "NVE", "country": "Norway", "color": "#e377c2"},
    "pl_imgw": {"name": "IMGW", "country": "Poland", "color": "#7f7f7f"},
    "jp_mlit": {"name": "MLIT", "country": "Japan", "color": "#bcbd22"},
    "cz_chmi": {"name": "CHMI", "country": "Czechia", "color": "#17becf"},
    "th_thaiwater": {"name": "ThaiWater", "country": "Thailand", "color": "#ff7f0e"},
    "ch_foen": {"name": "FOEN", "country": "Switzerland", "color": "#3366cc"},
    "lt_lhmt": {"name": "LHMT", "country": "Lithuania", "color": "#dc3912"},
    "ba_fhmzbih": {"name": "AVP Sava", "country": "Bosnia and Herzegovina", "color": "#109618"},
    "za_dws": {"name": "DWS", "country": "South Africa", "color": "#990099"},
}


def build_map(output_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    parquet_pattern = str(repo_root / "src/rivretrieve/_internal/providers/*/catalogue/stations.parquet")
    station_files = sorted(glob.glob(parquet_pattern))

    if not station_files:
        raise FileNotFoundError(f"No station parquet files found matching: {parquet_pattern}")

    frames = []
    for filepath in station_files:
        df = pl.read_parquet(filepath).select("provider_id", "station_id", "latitude", "longitude", "crs")
        frames.append(df)

    stations_df = pl.concat(frames)

    # Build unique provider list
    unique_providers = sorted(stations_df["provider_id"].unique().to_list())
    provider_to_idx = {pid: i for i, pid in enumerate(unique_providers)}

    providers_meta = []
    for pid in unique_providers:
        meta = PROVIDER_METADATA.get(pid, {"name": pid, "country": "Unknown", "color": "#3388ff"})
        count = int((stations_df["provider_id"] == pid).sum())
        providers_meta.append(
            {
                "id": pid,
                "name": meta["name"],
                "country": meta["country"],
                "color": meta["color"],
                "count": count,
            }
        )

    # Prepare compact station points: [lat_round, lon_round, station_id, provider_idx, crs_is_unknown]
    # Round lat/lon to 4 decimal places (~11m precision), sufficient for gauge exploration and reduces JSON size
    records = []
    for row in stations_df.iter_rows(named=True):
        lat = round(row["latitude"], 4)
        lon = round(row["longitude"], 4)
        pid_idx = provider_to_idx[row["provider_id"]]
        is_unknown_crs = 1 if row.get("crs") == "unknown" else 0
        records.append([lat, lon, row["station_id"], pid_idx, is_unknown_crs])

    html_content = generate_html(providers_meta, records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Generated interactive map with {len(records):,} stations at {output_path}")


def generate_html(providers_meta: list[dict], records: list[list]) -> str:
    providers_json = json.dumps(providers_meta)
    records_json = json.dumps(records, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RivRetrieve Station Explorer</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
  <style>
    html, body {{
      height: 100%;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    #map {{
      height: 100%;
      width: 100%;
    }}
    .sidebar-toggle {{
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 1000;
      background: white;
      padding: 8px 14px;
      border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 6px;
      border: 1px solid #ddd;
    }}
    .panel {{
      position: absolute;
      top: 50px;
      right: 12px;
      z-index: 1000;
      background: white;
      padding: 16px;
      border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.2);
      width: 320px;
      max-height: calc(100% - 80px);
      display: flex;
      flex-direction: column;
      font-size: 13px;
      border: 1px solid #ddd;
      box-sizing: border-box;
    }}
    .panel.hidden {{
      display: none;
    }}
    .panel-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      font-size: 15px;
      font-weight: bold;
      color: #1a202c;
    }}
    .search-box {{
      width: 100%;
      padding: 7px 10px;
      border: 1px solid #ccc;
      border-radius: 5px;
      box-sizing: border-box;
      margin-bottom: 12px;
      font-size: 13px;
    }}
    .actions-bar {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      font-size: 12px;
    }}
    .actions-bar a {{
      color: #0284c7;
      text-decoration: none;
      cursor: pointer;
    }}
    .actions-bar a:hover {{
      text-decoration: underline;
    }}
    .provider-list {{
      overflow-y: auto;
      flex-grow: 1;
      padding-right: 4px;
    }}
    .provider-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 5px 0;
      border-bottom: 1px solid #f0f0f0;
    }}
    .provider-label {{
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      flex-grow: 1;
    }}
    .color-pill {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }}
    .provider-count {{
      color: #666;
      font-size: 11px;
      background: #eee;
      padding: 2px 6px;
      border-radius: 10px;
    }}
    .status-summary {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #e2e8f0;
      font-size: 12px;
      color: #4a5568;
      display: flex;
      justify-content: space-between;
      font-weight: 500;
    }}
    .leaflet-popup-content {{
      font-size: 13px;
      line-height: 1.45;
    }}
    .code-box {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      padding: 6px 8px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 11px;
      margin-top: 6px;
      white-space: pre-wrap;
      word-break: break-all;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <button id="toggle-panel" class="sidebar-toggle">Filters & Providers</button>
  <div id="panel" class="panel">
    <div class="panel-header">
      <span>RivRetrieve Stations</span>
    </div>
    <input type="text" id="search" class="search-box" placeholder="Search station ID..." />
    <div class="actions-bar">
      <span><strong>Select:</strong> <a id="select-all">All</a> | <a id="select-none">None</a></span>
      <span id="rendered-count">Loading...</span>
    </div>
    <div id="provider-list" class="provider-list"></div>
    <div class="status-summary">
      <span>Total catalogued:</span>
      <span id="total-count">{len(records):,}</span>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script>
    const providers = {providers_json};
    const stations = {records_json};

    const map = L.map('map', {{
      center: [25, 0],
      zoom: 2,
      minZoom: 2,
      maxZoom: 18,
    }});

    // Basemap tile layers (completely free, no API key required)
    const esriTopo = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), and the GIS User Community',
      maxZoom: 18
    }});

    const osm = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19
    }});

    const esriGray = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
      maxZoom: 16
    }});

    const esriImagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 18
    }});

    // Add default basemap
    esriTopo.addTo(map);

    // Basemap selector control
    const baseMaps = {{
      "Topographic (Esri)": esriTopo,
      "OpenStreetMap": osm,
      "Light Gray Canvas (Esri)": esriGray,
      "Satellite Imagery (Esri)": esriImagery
    }};
    L.control.layers(baseMaps, null, {{ position: 'bottomleft' }}).addTo(map);

    const clusterGroup = L.markerClusterGroup({{
      chunkedLoading: true,
      chunkInterval: 50,
      chunkDelay: 20,
      maxClusterRadius: 45,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      removeOutsideVisibleBounds: true,
    }});

    map.addLayer(clusterGroup);

    const activeProviders = new Set(providers.map((_, i) => i));
    let stationMarkers = [];

    // Populate provider list in sidebar
    const listContainer = document.getElementById('provider-list');
    providers.forEach((p, idx) => {{
      const div = document.createElement('div');
      div.className = 'provider-item';
      div.innerHTML = `
        <label class="provider-label">
          <input type="checkbox" data-idx="${{idx}}" checked />
          <span class="color-pill" style="background:${{p.color}}"></span>
          <span><strong>${{p.name}}</strong> (${{p.country}})</span>
        </label>
        <span class="provider-count">${{p.count.toLocaleString()}}</span>
      `;
      listContainer.appendChild(div);
    }});

    function makePopup(stn) {{
      const [lat, lon, stnId, pIdx, isUnknownCrs] = stn;
      const prov = providers[pIdx];
      const crsWarning = isUnknownCrs ? '<div style="color:orange;font-size:11px;margin-top:2px;">⚠️ Unknown CRS (plotted as EPSG:4326)</div>' : '';
      return `
        <div>
          <div style="font-size:14px;font-weight:bold;color:#0f172a;">${{stnId}}</div>
          <div style="color:#475569;font-size:12px;"><strong>${{prov.name}}</strong> &bull; ${{prov.country}}</div>
          <div style="font-size:12px;margin-top:4px;color:#334155;">
            Lat: ${{lat}}, Lon: ${{lon}}
            ${{crsWarning}}
          </div>
          <div class="code-box">import rivretrieve as rr<br>g = rr.find(provider="${{prov.id}}", station="${{stnId}}")</div>
        </div>
      `;
    }}

    function rebuildMarkers() {{
      clusterGroup.clearLayers();
      const newMarkers = [];
      const searchTerm = document.getElementById('search').value.trim().toLowerCase();

      for (let i = 0; i < stations.length; i++) {{
        const stn = stations[i];
        const [lat, lon, stnId, pIdx] = stn;
        if (!activeProviders.has(pIdx)) continue;
        if (searchTerm && !stnId.toLowerCase().includes(searchTerm)) continue;

        const marker = L.circleMarker([lat, lon], {{
          radius: 5,
          fillColor: providers[pIdx].color,
          color: "#fff",
          weight: 1,
          opacity: 1,
          fillOpacity: 0.8
        }});
        marker.bindPopup(() => makePopup(stn));
        newMarkers.push(marker);
      }}

      clusterGroup.addLayers(newMarkers);
      document.getElementById('rendered-count').innerText = `${{newMarkers.length.toLocaleString()}} shown`;
    }}

    // Initial marker render
    rebuildMarkers();

    // Event listeners
    listContainer.addEventListener('change', (e) => {{
      if (e.target.matches('input[type="checkbox"]')) {{
        const idx = parseInt(e.target.dataset.idx, 10);
        if (e.target.checked) {{
          activeProviders.add(idx);
        }} else {{
          activeProviders.delete(idx);
        }}
        rebuildMarkers();
      }}
    }});

    document.getElementById('select-all').addEventListener('click', () => {{
      listContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {{
        cb.checked = true;
      }});
      providers.forEach((_, i) => activeProviders.add(i));
      rebuildMarkers();
    }});

    document.getElementById('select-none').addEventListener('click', () => {{
      listContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {{
        cb.checked = false;
      }});
      activeProviders.clear();
      rebuildMarkers();
    }});

    let searchTimeout = null;
    document.getElementById('search').addEventListener('input', () => {{
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(rebuildMarkers, 300);
    }});

    const panel = document.getElementById('panel');
    document.getElementById('toggle-panel').addEventListener('click', () => {{
      panel.classList.toggle('hidden');
    }});
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "assets" / "stations_map.html"
    build_map(out)
