# Westlake Leak Image Viewer

A [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) for browsing gas/liquid leak inspection images. It pairs each image with the leak classification results from a Unity Catalog table. Reviewers can filter by leak status and point of interest (POI), page through thumbnails grouped by POI, and click any image to open a full-screen review view with the model's classification and evidence.

Built with [Dash](https://dash.plotly.com/) + [Dash Bootstrap Components](https://dash-bootstrap-components.opensource.faculty.ai/) and the [Databricks SDK for Python](https://docs.databricks.com/en/dev-tools/sdk-python.html).

## Features

- **Summary stats**: total events, leaks detected, images available, and number of POIs
- **Filters**: leak status (All / Leak Detected / No Leak) and point of interest
- **Paginated image grid**: 12 images per page, grouped by POI, with leak and confidence badges and the capture timestamp on each card
- **Full-screen review view**: click a thumbnail to load a larger version (up to 1800px) next to:
  - Point of interest and capture time
  - Whether the current model suspected a leak
  - Leak type and the model's evidence for the classification
  - Source filename
- **Fast startup**: at startup the app only lists the volume directory and runs one metadata query. Thumbnails are cached in memory by a background thread, and enlarged images are loaded when clicked (LRU cache of 48).

## Architecture

```
┌──────────────────────────┐      SQL (Statement Execution API)     ┌──────────────────────────────┐
│                          │ ─────────────────────────────────────▶ │ SQL Warehouse                │
│  Dash app (app.py)       │                                        │  silver_liquid_leak_results  │
│  Databricks Apps runtime │                                        └──────────────────────────────┘
│                          │      Files API (list / download)       ┌──────────────────────────────┐
│                          │ ─────────────────────────────────────▶ │ UC Volume: documents/        │
└──────────────────────────┘                                        │  OneDrive_1_10-13-2026/*.jpg │
                                                                    └──────────────────────────────┘
```

| Component | Value |
|-----------|-------|
| Catalog / schema | `stable_classic_wg38i9_catalog.westlake_gas_leakage_2` |
| Results table | `silver_liquid_leak_results` |
| Image volume path | `/Volumes/stable_classic_wg38i9_catalog/westlake_gas_leakage_2/documents/OneDrive_1_10-13-2026` |
| SQL warehouse | set with the `DATABRICKS_WAREHOUSE_ID` env var (see `app.yaml`) |

### Expected table columns

The app reads these columns from the results table:

| Column | Used for |
|--------|----------|
| `event_id` | Event identifier |
| `point_of_interest_id` | POI grouping and filter (cast to `INT`) |
| `leaked` | Leak status (`1.0` → "Yes", anything else → "No") |
| `confidence_level` | Confidence badge |
| `leak_suspected` | "Current model said leak?" in the review view |
| `created_on_date_time` | Capture timestamp and sort order |
| `filename` | Matched against `.jpg` files in the volume |
| `leak_type` | Leak type shown in the review view |
| `evidence_for_classification` | Model evidence shown in the review view |

Only rows whose `filename` exists in the volume are shown in the grid.

## Project structure

```
.
├── app.py            # Dash application (data loading, layout, callbacks)
├── app.yaml          # Databricks Apps run command + environment
├── requirements.txt  # Python dependencies
└── README.md
```

## Deploying to Databricks Apps

### 1. App resources

Give the app's service principal access to:

| Resource name | Type | Permission |
|---------------|------|------------|
| `sql-warehouse` | SQL warehouse | `CAN_USE` |
| `silver-table` | UC table `...westlake_gas_leakage_2.silver_liquid_leak_results` | `SELECT` |
| `documents-volume` | UC volume `...westlake_gas_leakage_2.documents` | `READ_VOLUME` |

### 2. Configure

Set the warehouse ID in `app.yaml`:

```yaml
command:
  - python
  - app.py
env:
  - name: DATABRICKS_WAREHOUSE_ID
    value: "<your-warehouse-id>"
```

To point the app at a different catalog, schema, table, or volume folder, edit the constants at the top of `app.py` (`CATALOG`, `SCHEMA`, `TABLE`, `VOLUME_DIR`).

### 3. Deploy

```bash
# Upload source to the workspace
databricks sync . /Workspace/Users/<you>/westlake-leak-image-viewer

# Create the app (first time only)
databricks apps create westlake-leak-image-viewer

# Deploy
databricks apps deploy westlake-leak-image-viewer \
  --source-code-path /Workspace/Users/<you>/westlake-leak-image-viewer
```

## Running locally

```bash
pip install dash dash-bootstrap-components databricks-sdk pandas Pillow

# Authenticate with a Databricks CLI profile (or set DATABRICKS_HOST / DATABRICKS_TOKEN)
export DATABRICKS_CONFIG_PROFILE=<your-profile>
export DATABRICKS_WAREHOUSE_ID=<your-warehouse-id>

python app.py   # serves on http://localhost:8000 (override with APP_PORT)
```

## Configuration reference

| Setting | Where | Default |
|---------|-------|---------|
| `DATABRICKS_WAREHOUSE_ID` | env var | `4c06524b26564b9c` |
| `APP_PORT` | env var | `8000` |
| `PAGE_SIZE` | `app.py` | `12` |
| `THUMB_SIZE` | `app.py` | `280×280` |
| `FULL_MAX` | `app.py` | `1800×1800` |
