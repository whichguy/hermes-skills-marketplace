# USAW Google Drive Results Folder IDs

All confirmed Google Drive folder IDs for USAW national event results.

## 2026 Events

| Event | Folder Name | Drive ID | Status |
|-------|-------------|----------|--------|
| NCW | `2026 - NCW - Results` | `14ncrwEnqErUKGomckAdG_LOT0qEbRomI` | ✅ Available |
| VWS1 | `2026 - VWS1 - Results` | `1QtBcE-JuPc2Z9tijY0nRKDZhGDtNACjN` | ✅ Available |
| Masters & Uni | `2026 - Masters & Uni - Results` | `1D5-iyB8mfeppFYkIcQWu0AWnEYX-Dx8L` | ✅ Available |
| VWS2 | — | — | ⏳ TBA (event Sep 2026) |
| WZA | — | — | ⏳ TBA (event Sep 2026) |
| Finals | — | — | ⏳ TBA (event Dec 2026) |

## 2025 Events

| Event | Drive ID |
|-------|----------|
| NCW | `18HK_3x1cyoqQoEo-TEetR7CqJfRwOS6R` |
| VWS1 / NUC | `1-WSryPzPAbjLh9_5PiEHdjD7gllEA0Fg` |
| VWS2 | `1oqYeNFdjQODniXF6L3sdHxQZYJT27bs1` |
| Finals / UMWF | `1L693h3LdsDwl7IVe8tZEIp1wPjQzWTmO` |
| Masters | `1LJRAuGrYjInOSqHNmRjir7J-1muOdH0_` |
| WZA SoCal | `1Dly4mcFcv0qMi0tgGLOGlLch0M6LyOHn` |

## 2024 Events

| Event | Drive ID |
|-------|----------|
| North American Open Finals | `1-2RoAgqCwlWmmuMKfigUVpO2qJfH56ch` |
| North American Open Series 2 | `1-CIwhKK8-k4fjCcsKQLkT1t4Jc4puNKb` |
| National Championships Week | `1-8XjuUrdFvOJBT6VFhErcvMPNP_CvD54` |
| North American Series 1 / NUC | `1VO6ixF3Q2udtz8w86kiNPlJ4DPr_aHXA` |
| Masters Nationals | `1oiKS89-cHIiVLfp_JWgmfxDAIldLRUqm` |

## Access Methods

### Google Drive API (authenticated)
```bash
GAPI() {
  uv run --quiet \
    --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
    python ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/google-workspace/scripts/google_api.py "$@"
}

# Search for files in a folder
GAPI --account personal drive search "2026 - NCW - Results"

# Download a file by ID
GAPI --account personal drive download {FILE_ID} --output /tmp/results.pdf
```

### Public web access
Folders are shared publicly: `https://drive.google.com/drive/folders/{FOLDER_ID}`

### Via usaw_results_parser.py (this skill)
```bash
uv run --with pymupdf --with requests \
  python scripts/usaw_results_parser.py --folder-id 14ncrwEnqErUKGomckAdG_LOT0qEbRomI --json
```

## Folder Naming Convention
```
{YEAR} - {EVENT_ABBR} - Results
```

## Historical Archive
All results folders (2012–present) are linked from `usaweightlifting.org/results`. Pre-2018 results are on AWS S3 (direct PDF/Excel links).