from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz, re, io, base64
from PIL import Image
import numpy as np

app = Flask(__name__)
CORS(app)

def get_thumbs(arr, x0, ancho, scale, n):
    best = []
    for off in [0, 27, 55, 82, 110, 137]:
        xc = max(0, int((x0 + off) * scale))
        xe = min(arr.shape[1], xc + int(ancho * scale))
        if xe <= xc: continue
        strip = arr[:, xc:xe, :]
        rd = (strip.min(axis=2) < 150).any(axis=1)
        t = []; in_g = False
        for i, v in enumerate(rd):
            y = i / scale
            if v and not in_g: in_g = True; t0 = y
            elif not v and in_g:
                in_g = False
                if y - t0 > 8: t.append(t0)
        if len(t) >= len(best) and len(t) >= int(n * 0.5):
            best = t
    return best

def fix_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    OX = 86.0; PX = 27.5; W = 22.5; H2 = 24.67
    total = 0; log = []

    for pi in range(len(doc)):
        page = doc[pi]; H = page.rect.height
        arr = np.array(Image.open(
            io.BytesIO(page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"))
        ))
        lks = page.get_links()
        if not lks: continue

        rows = {}
        for l in lks:
            r = l["from"]; k = round(r.y0, 2)
            if k not in rows: rows[k] = []
            rows[k].append(r)
        sy = sorted(rows.keys())

        ty = get_thumbs(arr, rows[sy[0]][0].x0 + OX, W, 3, len(sy))
        if not ty:
            log.append(f"P{pi+1}: sin thumbs"); continue

        paso = (ty[-1] - ty[0]) / (len(ty) - 1) if len(ty) > 1 else 32.5
        while len(ty) < len(sy): ty.append(ty[-1] + paso)

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
        for ri, (yl, yk) in enumerate(zip(sy, syt)):
            if ri >= len(ty): break
            ytp = H - ty[ri]; ybp = ytp - H2
            rrow = sorted(ro[yk], key=lambda p: p["x0"])
            x0r = rows[yl][0].x0
            for ci, p in enumerate(rrow):
                nx0 = x0r + OX + ci * PX; nx1 = nx0 + W
                os = p["m"].group(0)
                ns = f"/Rect [ {nx0:.4f} {ytp:.4f} {nx1:.4f} {ybp:.4f} ]"
                npo = npo.replace(os, ns, 1); rep += 1

        if rep > 0:
            doc.update_object(px, npo)
            total += rep
            log.append(f"P{pi+1}: {rep} enlaces")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), total, log

@app.route("/fix", methods=["POST", "OPTIONS"])
def fix_endpoint():
    if request.method == "OPTIONS":
        return "", 204
    try:
        data = request.get_json()
        pdf_b64 = data.get("pdf")
        if not pdf_b64:
            return jsonify({"error": "No PDF provided"}), 400
        pdf_bytes = base64.b64decode(pdf_b64)
        fixed_bytes, total, log = fix_pdf(pdf_bytes)
        return jsonify({
            "pdf": base64.b64encode(fixed_bytes).decode(),
            "total": total,
            "log": log
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
