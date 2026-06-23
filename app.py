# v4 - X-only linear transform, no image rendering needed
from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz, re, io, base64

app = Flask(__name__)
CORS(app)

# Transformación lineal calibrada: thumb_x = A * link_x + B
# Medida pixel-a-pixel en GGZ y SYNTSN (358 links, 0 errores en X)
A_X = 1.116993
B_X = -12.229
ANCHO = 22.5  # ancho del área clickeable

def fix_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = 0; log = []

    for pi in range(len(doc)):
        page = doc[pi]
        page_xref = page.xref
        page_obj = doc.xref_object(page_xref)

        rr = re.compile(r"/Rect \[ ([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) \]")
        parsed = []
        for m in rr.finditer(page_obj):
            x0=float(m.group(1)); yT=float(m.group(2))
            x1=float(m.group(3)); yB=float(m.group(4))
            if yT > yB and x1 > x0:
                parsed.append({"m": m, "x0": x0, "yT": yT, "yB": yB})

        if not parsed:
            continue

        npo = page_obj; rep = 0
        for p in parsed:
            new_x0 = A_X * p["x0"] + B_X
            new_x1 = new_x0 + ANCHO
            os = p["m"].group(0)
            ns = f"/Rect [ {new_x0:.4f} {p['yT']:.4f} {new_x1:.4f} {p['yB']:.4f} ]"
            npo = npo.replace(os, ns, 1)
            rep += 1

        if rep > 0:
            doc.update_object(page_xref, npo)
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
    return jsonify({"status": "ok", "version": "4.0-xonly"})

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
