"""
WeasyPrint PDF service.

One endpoint. POST HTML, get a PDF back. It exists so n8n can turn the
manifesto into a PDF with an HTTP Request node, exactly the way it was calling
the paid API, with no size ceiling and no per-document cost.

Deliberately accepts a RAW text/html body as well as JSON. Posting raw HTML
avoids JSON-escaping a large document inside an n8n expression, which is where
this kind of integration usually goes wrong.
"""

import os
import logging
from io import BytesIO

from flask import Flask, request, send_file, jsonify
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Set in docker-compose. The n8n side cannot read environment variables, so the
# matching value is hardcoded in the workflow; that asymmetry is fine, this
# service reads env normally.
TOKEN = os.environ.get("PDF_TOKEN", "")

# Loaded once at boot rather than per request: font configuration is the
# expensive part of a WeasyPrint render.
FONTS = FontConfiguration()

# An optional house stylesheet applied to every document, so the n8n workflow
# can send plain semantic HTML and let the container own the typography.
BASE_CSS_PATH = os.environ.get("BASE_CSS", "/app/css/manifesto_print.css")
BASE_CSS = None
if os.path.exists(BASE_CSS_PATH):
    BASE_CSS = CSS(filename=BASE_CSS_PATH, font_config=FONTS)
    app.logger.info("base stylesheet loaded: %s", BASE_CSS_PATH)


@app.get("/health")
def health():
    import weasyprint
    return jsonify(ok=True, weasyprint=weasyprint.__version__,
                   base_css=bool(BASE_CSS))


@app.post("/pdf")
def pdf():
    if TOKEN and request.headers.get("X-Auth-Token") != TOKEN:
        return jsonify(error="unauthorised"), 401

    # Two accepted shapes. Raw is preferred.
    if request.is_json:
        body = request.get_json(silent=True) or {}
        html_text = body.get("html", "")
        filename = body.get("filename", "document.pdf")
        base_url = body.get("base_url")
    else:
        html_text = request.get_data(as_text=True)
        filename = request.headers.get("X-Filename", "document.pdf")
        base_url = request.headers.get("X-Base-Url")

    if not html_text.strip():
        return jsonify(error="empty html body"), 400

    # base_url is how relative <img src> and <link href> are resolved. Without
    # it, a relative path resolves against nothing and the asset is dropped in
    # silence, which reads as "the logo just didn't appear".
    try:
        doc = HTML(string=html_text, base_url=base_url)
        out = BytesIO()
        doc.write_pdf(out,
                      stylesheets=[BASE_CSS] if BASE_CSS else None,
                      font_config=FONTS,
                      pdf_variant="pdf/a-3b" if request.headers.get("X-Archival") else None)
        out.seek(0)
    except Exception as exc:                              # noqa: BLE001
        app.logger.exception("render failed")
        return jsonify(error=str(exc)), 500

    size = out.getbuffer().nbytes
    app.logger.info("rendered %s (%.1f KB)", filename, size / 1024)

    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    return send_file(out, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


if __name__ == "__main__":
    # Dev entrypoint only; the container runs gunicorn. PORT is honoured here
    # too so local behaviour matches Render, which injects it.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
