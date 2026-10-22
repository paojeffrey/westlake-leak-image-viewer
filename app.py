import os
import io
import base64
import threading
from functools import lru_cache

import dash
from dash import dcc, html, Input, Output, State, ALL, ctx, no_update
import dash_bootstrap_components as dbc
import pandas as pd
from PIL import Image
from databricks.sdk import WorkspaceClient

# ── Configuration ────────────────────────────────────────
# NOTE: These values point at the Databricks FE demo workspace. Westlake's
# workspace uses different catalog/schema/table/volume names and a different
# warehouse — update all of them (and app.yaml) before deploying there.
CATALOG = "stable_classic_wg38i9_catalog"
SCHEMA = "westlake_gas_leakage_2"
TABLE = f"{CATALOG}.{SCHEMA}.silver_liquid_leak_results"
VOLUME_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/documents/OneDrive_1_10-13-2026"
THUMB_SIZE = (280, 280)
FULL_MAX = (1800, 1800)  # enlarged review view
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "4c06524b26564b9c")
PAGE_SIZE = 12

w = WorkspaceClient()
_b64_cache: dict[str, str | None] = {}
_lock = threading.Lock()
_available: set[str] = set()

# ── Palette (Southwest-inspired) ─────────────────────────
NAVY = "#111B2E"
DEEP_BLUE = "#1B3A6B"
RED = "#C62828"
GOLD = "#F9A825"
LIGHT = "#F5F7FA"
WHITE = "#FFFFFF"
SHADOW = "0 2px 12px rgba(27,58,107,0.10)"


# ── Data helpers ─────────────────────────────────────────
def _query_metadata() -> pd.DataFrame:
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=f"""
            SELECT
                event_id,
                CAST(point_of_interest_id AS INT) AS poi,
                CASE WHEN leaked = 1.0 THEN 'Yes' ELSE 'No' END AS leak,
                confidence_level, leak_suspected,
                CAST(created_on_date_time AS STRING) AS ts,
                filename, leak_type, evidence_for_classification
            FROM {TABLE}
            ORDER BY poi, created_on_date_time DESC
        """,
        wait_timeout="50s",
    )
    cols = [c.name for c in resp.manifest.schema.columns]
    rows = [dict(zip(cols, r)) for r in (resp.result.data_array or [])]
    return pd.DataFrame(rows)


def _index_volume():
    """Fast directory listing — no image data downloaded."""
    global _available
    try:
        for entry in w.files.list_directory_contents(VOLUME_DIR):
            if entry.name and entry.name.lower().endswith(".jpg"):
                _available.add(entry.name)
    except Exception as e:
        print(f"[WARN] Volume index failed: {e}")
    print(f"  {len(_available)} image files indexed.")


def _load_b64(filename: str) -> str | None:
    with _lock:
        if filename in _b64_cache:
            return _b64_cache[filename]
    if _available and filename not in _available:
        with _lock:
            _b64_cache[filename] = None
        return None
    try:
        resp = w.files.download(f"{VOLUME_DIR}/{filename}")
        img = Image.open(io.BytesIO(resp.contents.read()))
        img.thumbnail(THUMB_SIZE)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        uri = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
        with _lock:
            _b64_cache[filename] = uri
        return uri
    except Exception:
        with _lock:
            _b64_cache[filename] = None
        return None


@lru_cache(maxsize=48)
def _load_full_b64(filename: str) -> str | None:
    """Larger version of an image for the enlarged review view (loaded on click)."""
    try:
        resp = w.files.download(f"{VOLUME_DIR}/{filename}")
        img = Image.open(io.BytesIO(resp.contents.read())).convert("RGB")
        img.thumbnail(FULL_MAX)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception as e:
        print(f"[WARN] Full image load failed for {filename}: {e}")
        return None


# ── Startup (fast: metadata + file list, no image bytes) ─
print("Indexing volume files...")
_index_volume()
print("Loading metadata...")
meta = _query_metadata()
meta["has_image"] = meta["filename"].apply(
    lambda f: bool(f and f in _available)
)
print(f"  {len(meta)} rows, {meta['has_image'].sum()} with images.")

pois = sorted(meta["poi"].dropna().unique().tolist())
poi_opts = [{"label": "All POIs", "value": "All"}] + [
    {"label": f"POI {p}", "value": str(p)} for p in pois
]
leak_opts = [
    {"label": "All Status", "value": "All"},
    {"label": "Leak Detected", "value": "Yes"},
    {"label": "No Leak", "value": "No"},
]

n_events = len(meta)
n_leaks = int((meta["leak"] == "Yes").sum())
n_images = int(meta["has_image"].sum())
n_pois = len(pois)

# Background pre-cache (won't block startup)
threading.Thread(
    target=lambda: [
        _load_b64(f) for f in meta.loc[meta["has_image"], "filename"].unique()
    ],
    daemon=True,
).start()


# ── Custom CSS ───────────────────────────────────────────
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
body{font-family:'Inter',sans-serif;background:""" + LIGHT + """;margin:0}
.hero{background:linear-gradient(135deg,""" + NAVY + """ 0%,""" + DEEP_BLUE + """ 55%,#2D5AA0 100%);
  color:#fff;padding:2.2rem 2.5rem 1.8rem;margin-bottom:1.5rem;
  box-shadow:0 4px 24px rgba(27,58,107,0.3);position:relative;overflow:hidden}
.hero::after{content:'';position:absolute;right:-60px;top:-60px;width:280px;height:280px;
  background:""" + GOLD + """;opacity:0.10;border-radius:50%}
.hero h1{font-weight:800;font-size:1.75rem;margin:0 0 .25rem;letter-spacing:-.02em}
.hero p{opacity:.85;font-size:.92rem;margin:0;font-weight:400}
.gold-bar{height:4px;background:linear-gradient(90deg,""" + GOLD + """,transparent);margin-top:.8rem;border-radius:2px;width:120px}
.stat-card{background:#fff;border-radius:.9rem;padding:1.1rem 1.2rem;box-shadow:""" + SHADOW + """;
  text-align:center;transition:transform .15s,box-shadow .15s;border-left:4px solid transparent}
.stat-card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(27,58,107,.15)}
.stat-card.accent{border-left-color:""" + RED + """}
.sn{font-size:1.9rem;font-weight:800;color:""" + DEEP_BLUE + """;line-height:1.1}
.sn.red{color:""" + RED + """}
.sl{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:#7A8BA5;font-weight:600;margin-top:.25rem}
.fbar{background:#fff;border-radius:.9rem;padding:1.1rem 1.4rem;box-shadow:""" + SHADOW + """;margin-bottom:1.4rem}
.fbar label{font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:""" + DEEP_BLUE + """;margin-bottom:.35rem}
.icard{background:#fff;border-radius:.9rem;overflow:hidden;box-shadow:""" + SHADOW + """;
  transition:transform .2s,box-shadow .2s,border-color .2s;border:2px solid transparent}
.icard:hover{transform:translateY(-4px);box-shadow:0 8px 30px rgba(27,58,107,.18);border-color:""" + GOLD + """}
.icard img{width:100%;height:210px;object-fit:cover;background:#E8ECF1}
.icb{padding:.85rem .95rem}
.icb h6{font-weight:700;color:""" + DEEP_BLUE + """;margin-bottom:.45rem;font-size:.88rem}
.bl{display:inline-block;padding:.2rem .6rem;border-radius:2rem;font-size:.68rem;font-weight:600;letter-spacing:.03em;margin-right:.35rem}
.bl-y{background:""" + RED + """;color:#fff}
.bl-n{background:#2E7D32;color:#fff}
.bl-c{background:#E3F2FD;color:#1565C0}
.poi-hdr{font-weight:700;font-size:1.05rem;color:""" + DEEP_BLUE + """;padding:.5rem 0;margin-top:1.4rem;
  margin-bottom:.7rem;border-bottom:3px solid """ + GOLD + """;display:inline-block}
.pgbar{display:flex;justify-content:center;align-items:center;gap:.6rem;padding:1.2rem 0}
.pbtn{background:#fff;border:2px solid #D0D8E5;border-radius:.55rem;padding:.4rem 1.1rem;
  font-weight:600;font-size:.82rem;color:""" + DEEP_BLUE + """;cursor:pointer;transition:all .15s}
.pbtn:hover{border-color:""" + DEEP_BLUE + """;background:""" + DEEP_BLUE + """;color:#fff}
.pinfo{font-size:.82rem;color:#7A8BA5;font-weight:500}
.rsum{font-size:.88rem;font-weight:600;color:""" + DEEP_BLUE + """;margin-bottom:.4rem}
.apply-btn{background:""" + DEEP_BLUE + """;color:#fff;border:2px solid """ + DEEP_BLUE + """;
  border-radius:.55rem;padding:.5rem 1.6rem;font-weight:600;font-size:.82rem;cursor:pointer;
  transition:all .15s;margin-top:1.55rem}
.apply-btn:hover{background:""" + GOLD + """;color:""" + NAVY + """;border-color:""" + GOLD + """}
.empty-img{height:210px;background:#E8ECF1;display:flex;align-items:center;justify-content:center;
  color:#999;font-size:.85rem}
.img-open{position:relative;cursor:zoom-in}
.img-open .hint{position:absolute;right:.6rem;bottom:.6rem;background:rgba(17,27,46,.75);color:#fff;
  font-size:.7rem;font-weight:600;padding:.25rem .55rem;border-radius:2rem;opacity:0;transition:opacity .15s}
.icard:hover .img-open .hint{opacity:1}
.viewer .modal-content{background:""" + NAVY + """;color:#fff;border:0}
.viewer .modal-header{border-bottom:1px solid rgba(255,255,255,.12);gap:1rem;justify-content:flex-start}
.back-btn{background:""" + GOLD + """;color:""" + NAVY + """;border:0;border-radius:.55rem;padding:.5rem 1.3rem;
  font-weight:700;font-size:.9rem;cursor:pointer}
.back-btn:hover{background:#fff}
.vtitle{font-weight:700;font-size:1.05rem}
.vimg{width:100%;max-height:78vh;object-fit:contain;border-radius:.6rem;background:#000}
.vside{background:rgba(255,255,255,.06);border-radius:.8rem;padding:1.1rem 1.2rem;font-size:.88rem}
.vside dt{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:#9FB0CC;font-weight:600;margin-top:.8rem}
.vside dd{margin:0;word-break:break-word}
"""


# ── Dash app ─────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Westlake Leak Image Viewer",
    suppress_callback_exceptions=True,
)

app.index_string = (
    "<!DOCTYPE html><html><head>{%metas%}<title>{%title%}</title>"
    "{%favicon%}{%css%}<style>" + CSS + "</style></head>"
    "<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"
)

app.layout = html.Div([
    # Hero
    html.Div([
        html.H1("Westlake Gas Leak Inspection"),
        html.P("Visual inspection image browser \u2014 filter by leak status and point of interest"),
        html.Div(className="gold-bar"),
    ], className="hero"),

    html.Div([
        # Stats row
        dbc.Row([
            dbc.Col(html.Div([
                html.Div(str(n_events), className="sn"),
                html.Div("Total Events", className="sl"),
            ], className="stat-card"), md=3, sm=6, xs=6),
            dbc.Col(html.Div([
                html.Div(str(n_leaks), className="sn red"),
                html.Div("Leaks Detected", className="sl"),
            ], className="stat-card accent"), md=3, sm=6, xs=6),
            dbc.Col(html.Div([
                html.Div(str(n_images), className="sn"),
                html.Div("Images Available", className="sl"),
            ], className="stat-card"), md=3, sm=6, xs=6),
            dbc.Col(html.Div([
                html.Div(str(n_pois), className="sn"),
                html.Div("Points of Interest", className="sl"),
            ], className="stat-card"), md=3, sm=6, xs=6),
        ], className="mb-4 g-3"),

        # Filter bar
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Leak Status"),
                    dcc.Dropdown(id="leak-filter", options=leak_opts,
                                 value="All", clearable=False),
                ], md=3, sm=6),
                dbc.Col([
                    html.Label("Point of Interest"),
                    dcc.Dropdown(id="poi-filter", options=poi_opts,
                                 value="All", clearable=False),
                ], md=3, sm=6),
                dbc.Col(
                    html.Button("Apply Filters", id="apply-btn", className="apply-btn"),
                    md=2,
                ),
            ], className="align-items-end"),
        ], className="fbar"),

        # Results
        html.Div(id="rsum", className="rsum"),
        dbc.Spinner(
            html.Div(id="image-grid"),
            color="primary",
            spinner_style={"width": "2.5rem", "height": "2.5rem"},
        ),

        # Pagination (always in DOM; visibility toggled)
        html.Div([
            html.Button("\u2190  Previous", id="prev-btn", className="pbtn", n_clicks=0),
            html.Span("", id="page-info", className="pinfo"),
            html.Button("Next  \u2192", id="next-btn", className="pbtn", n_clicks=0),
        ], className="pgbar"),

        dcc.Store(id="page", data=1),
        dcc.Store(id="idx", data=[]),

        # Enlarged image review view
        dbc.Modal([
            dbc.ModalHeader([
                html.Button("\u2190  Back", id="back-btn", className="back-btn", n_clicks=0),
                html.Div(id="viewer-title", className="vtitle"),
            ], close_button=False),
            dbc.ModalBody(dbc.Spinner(html.Div(id="viewer-body"), color="warning")),
        ], id="viewer", is_open=False, fullscreen=True, className="viewer", keyboard=True),
    ], style={"padding": "0 2rem 2rem", "maxWidth": "1400px", "margin": "0 auto"}),
])


# ── Card builder ─────────────────────────────────────────
def _card(row):
    fn = row.get("filename")
    uri = _load_b64(fn) if fn else None
    leak_cls = "bl bl-y" if row["leak"] == "Yes" else "bl bl-n"
    leak_txt = "LEAK DETECTED" if row["leak"] == "Yes" else "NO LEAK"
    img_el = (
        html.Div([
            html.Img(src=uri, style={"width": "100%", "height": "210px",
                                      "objectFit": "cover", "background": "#E8ECF1"}),
            html.Span("Click to enlarge", className="hint"),
        ], id={"type": "img-open", "index": int(row.name)}, n_clicks=0, className="img-open",
            title="Click to enlarge")
        if uri else html.Div("Image not available", className="empty-img")
    )
    return dbc.Col(
        html.Div([
            img_el,
            html.Div([
                html.H6(f"POI {row['poi']}"),
                html.Div([
                    html.Span(leak_txt, className=leak_cls),
                    html.Span(row["confidence_level"] or "", className="bl bl-c"),
                ]),
                html.Div(row["ts"] or "", style={"fontSize": ".73rem",
                                                   "color": "#7A8BA5", "marginTop": ".3rem"}),
            ], className="icb"),
        ], className="icard"),
        lg=3, md=4, sm=6, xs=12,
    )


# ── Callbacks ────────────────────────────────────────────
@app.callback(
    Output("idx", "data"),
    Output("page", "data"),
    Input("apply-btn", "n_clicks"),
    State("leak-filter", "value"),
    State("poi-filter", "value"),
    prevent_initial_call=False,
)
def apply_filters(_, leak_val, poi_val):
    df = meta
    if leak_val and leak_val != "All":
        df = df[df["leak"] == leak_val]
    if poi_val and poi_val != "All":
        df = df[df["poi"] == poi_val]
    df = df[df["has_image"]]
    return df.index.tolist(), 1


@app.callback(
    Output("image-grid", "children"),
    Output("rsum", "children"),
    Output("page-info", "children"),
    Output("prev-btn", "style"),
    Output("next-btn", "style"),
    Input("idx", "data"),
    Input("page", "data"),
)
def render(indices, pg):
    if not indices:
        hide = {"display": "none"}
        return (
            html.P("No images match the current filters.",
                   style={"color": "#999", "padding": "2rem 0", "textAlign": "center"}),
            "0 images found", "", hide, hide,
        )

    total = len(indices)
    pages = max(1, -(-total // PAGE_SIZE))
    pg = max(1, min(pg or 1, pages))
    lo = (pg - 1) * PAGE_SIZE
    hi = min(lo + PAGE_SIZE, total)
    df_page = meta.loc[indices[lo:hi]]

    sections = []
    for poi, grp in df_page.groupby("poi", sort=True):
        sections.append(html.Div(f"Point of Interest {poi}", className="poi-hdr"))
        sections.append(dbc.Row([_card(r) for _, r in grp.iterrows()], className="g-3"))

    show = {"display": "inline-block"}
    hide = {"display": "none"}
    return (
        html.Div(sections),
        f"Showing {lo + 1}\u2013{hi} of {total} image(s)",
        f"Page {pg} of {pages}",
        show if pg > 1 else hide,
        show if pg < pages else hide,
    )


@app.callback(
    Output("page", "data", allow_duplicate=True),
    Input("prev-btn", "n_clicks"),
    State("page", "data"),
    prevent_initial_call=True,
)
def prev(_, pg):
    return max(1, (pg or 1) - 1)


@app.callback(
    Output("page", "data", allow_duplicate=True),
    Input("next-btn", "n_clicks"),
    State("page", "data"),
    prevent_initial_call=True,
)
def nxt(_, pg):
    return (pg or 1) + 1


def _detail(label, value):
    return [html.Dt(label), html.Dd(value if value not in (None, "") else "\u2014")]


@app.callback(
    Output("viewer", "is_open"),
    Output("viewer-title", "children"),
    Output("viewer-body", "children"),
    Input({"type": "img-open", "index": ALL}, "n_clicks"),
    Input("back-btn", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_viewer(_open_clicks, _back_clicks):
    trig = ctx.triggered_id
    if trig == "back-btn":
        return False, no_update, no_update
    # Re-rendering the grid creates new cards with n_clicks=0; only react to a real click
    if not isinstance(trig, dict) or not ctx.triggered or not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update
    row = meta.loc[trig["index"]]
    uri = _load_full_b64(row["filename"]) or _load_b64(row["filename"])
    leak_cls = "bl bl-y" if row["leak"] == "Yes" else "bl bl-n"
    leak_txt = "LEAK DETECTED" if row["leak"] == "Yes" else "NO LEAK"
    image = (html.Img(src=uri, className="vimg") if uri
             else html.Div("Image not available", className="empty-img"))
    side = html.Div([
        html.Div([html.Span(leak_txt, className=leak_cls),
                  html.Span(row["confidence_level"] or "", className="bl bl-c")]),
        html.Dl(
            _detail("Point of interest", f"POI {row['poi']}")
            + _detail("Captured", row["ts"])
            + _detail("Current model said leak?", row["leak_suspected"])
            + _detail("Leak type (model)", row["leak_type"])
            + _detail("Model evidence", row["evidence_for_classification"])
            + _detail("File", row["filename"])
        ),
    ], className="vside")
    body = dbc.Row([dbc.Col(image, lg=9), dbc.Col(side, lg=3)], className="g-3")
    return True, f"POI {row['poi']} \u00b7 {row['ts'] or ''}", body


port = int(os.environ.get("APP_PORT", "8000"))
app.run(host="0.0.0.0", port=port, debug=False)
