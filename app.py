from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz, re, io, base64
from PIL import Image
import numpy as np

app = Flask(__name__)
CORS(app)

def detect_thumb_x_columns(arr, scale, page_width):
    x_start = int(page_width * 0.65 * scale)
    col_density = (arr[:, x_start:, :].min(axis=2) < 150).sum(axis=0)
    threshold = max(col_density) * 0.25 if col_density.max() > 0 else 1
    in_peak = False; peaks = []
    for i, v in enumerate(col_density):
        if v > threshold and not in_peak: in_peak = True; p0 = i
        elif v <= threshold and in_peak:
            in_peak = False
            peaks.append((x_start + (p0 + i) // 2) / scale)
    return peaks

def detect_thumb_y_rows(arr, scale, x_cols):
    best = []
    for xc_pt in x_cols[:4]:
        xc = max(0, int(xc_pt * scale) - int(8 * scale))
        xe = min(arr.shape[1], xc + int(20 * scale))
        strip = arr[:, xc:xe, :]
        rd = (strip.min(axis=2) < 150).any(axis=1)
        thumbs = []; in_g = False
        for i, v in enumerate(rd):
            y = i / scale
            if v and not in_g: in_g = True; t0 = y
            elif not v and in_g:
                in_g = False
                if y - t0 > 8: thumbs.append(t0)
        if len(thumbs) > len(best): best = thumbs
    return best

def fix_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    ANCHO = 22.5; ALTO = 24.67
    total = 0; log = []

    for pi in range(len(doc)):
        page = doc[pi]
        H = page.rect.height; W = page.rect.width
        scale = 3
        arr = np.array(Image.open(
            io.BytesIO(page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png"))
        ))

        links = page.get_links()
        if not links: continue

        rows = {}
        for lnk in links:
            r = lnk["from"]; k = round(r.y0, 2)
            if k not in rows: rows[k] = []
            rows[k].append(r)
        sorted_ys = sorted(rows.keys())

        # Detectar X de thumbnails desde la imagen
        x_cols = detect_thumb_x_columns(arr, scale, W)
        if not x_cols:
            log.append(f"P{pi+1}: sin columnas X"); continue
        x0_thumb = x_cols[0] - ANCHO / 2
        paso_x = (x_cols[1] - x_cols[0]) if len(x_cols) > 1 else 27.5

        # Detectar Y de thumbnails desde la imagen
        thumbs_y = detect_thumb_y_rows(arr, scale, x_cols)
        if not thumbs_y:
            log.append(f"P{pi+1}: sin filas Y"); continue

        paso_y = (thumbs_y[-1]-thumbs_y[0])/(len(thumbs_y)-1) if len(thumbs_y) > 1 else 32.5
        while len(thumbs_y) < len(sorted_ys):
            thumbs_y.append(thumbs_y[-1] + paso_y)

        # Modificar Rects via page object
        px = page.xref; po = doc.xref_object(px)
        rr = re.compile(r"/Rect \[ ([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) \]")
        parsed = [
            {"m": m, "x0": float(m.group(1)), "yT": float(m.group(2))}
            for m in rr.finditer(po)
            if float(m.group(2)) > float(m.group(4)) and float(m.group(3)) > float(m.group(1))
        ]
        ro = {}
        for p in parsed:
            k = round(p["yT"], 1)
            if k not in ro: ro[k] = []
            ro[k].append(p)
        syt = sorted(ro.keys(), reverse=True)

        npo = po; rep = 0
        for ri, (yl, yk) in enumerate(zip(sorted_ys, syt)):
            if ri >= len(thumbs_y): break
            ytp = H - thumbs_y[ri]; ybp = ytp - ALTO
            rrow = sorted(ro[yk], key=lambda p: p["x0"])
            for ci, p in enumerate(rrow):
                nx0 = x0_thumb + ci * paso_x
                nx1 = nx0 + ANCHO
                os = p["m"].group(0)
                ns = f"/Rect [ {nx0:.4f} {ytp:.4f} {nx1:.4f} {ybp:.4f} ]"
                npo = npo.replace(os, ns, 1); rep += 1

        if rep > 0:
            doc.update_object(px, npo)
            total += rep
            log.append(f"P{pi+1}: {rep} enlaces ({len(thumbs_y)} filas)")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), total, log

@app.route("/fix", methods=["POST", "OPTIONS"])
def fix_endpoint():
    if request.method == "OPTIONS":
        return "", 204
    try:
        data = request.get_json()
        if not data or not data.get("pdf"):
            return jsonify({"error": "No PDF provided"}), 400
        pdf_bytes = base64.b64decode(data["pdf"])
        fixed_bytes, total, log = fix_pdf(pdf_bytes)
        return jsonify({
            "pdf": base64.b64encode(fixed_bytes).decode(),
            "total": total,
            "log": log
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()[-500:]}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "2.0-imgdetect"})

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
