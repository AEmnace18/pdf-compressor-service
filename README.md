# Separate real-compression service prototype

This is a standalone Python service for **actual aggressive PDF compression**.

## What it does

This prototype is intentionally built for **scanned / image-heavy PDFs**.
Instead of just rewriting PDF structure, it:

1. renders each PDF page to an image
2. downsamples by level
3. JPEG-compresses each page
4. rebuilds a new PDF from the compressed page images

That is why it can shrink scan-heavy PDFs much more than your current inline route.

## Compression levels

- **light**
  - 170 DPI
  - JPEG quality 70
  - color
- **recommended**
  - 130 DPI
  - JPEG quality 52
  - color
- **strong**
  - 105 DPI
  - JPEG quality 36
  - grayscale

## Important limitation

This rasterizes pages.
That means:
- best for scans, signatures, stamped memos, photo PDFs
- not ideal for born-digital text PDFs
- text/search/selectability will be lost unless OCR is added later

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

## Test in browser / Postman

### Health
- `GET http://127.0.0.1:8001/health`

### Compress
- `POST http://127.0.0.1:8001/compress`
- multipart fields:
  - `file`
  - `level`
  - `filename`

## Suggested Next.js integration

Your Next route can forward the upload to this service instead of compressing inline.
That lets the heavy raster work live in a separate process.

See `next-proxy-route-example.ts` for a drop-in starting point.
