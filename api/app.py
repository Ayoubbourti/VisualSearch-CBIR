"""
API REST de calcul de descripteurs (Flask + Flask-RESTful).

Lancement :  python -m api.app          (écoute sur http://127.0.0.1:5001)
Production:  gunicorn -w 2 -b 0.0.0.0:5001 "api.app:create_app()"

Endpoints (POST multipart/form-data, champ « images » répétable pour traiter un ENSEMBLE d'images) :
  GET  /api/health               -> état du service
  GET  /api/descriptors/info     -> description des descripteurs (paramètres, structure du vecteur)
  POST /api/descriptors          -> couleur + texture + vecteur global
  POST /api/descriptors/color    -> histogramme, moments, couleurs dominantes
  POST /api/descriptors/texture  -> GLCM + histogramme LBP

Une erreur sur UNE image n'interrompt pas le lot : l'entrée concernée contient un champ « error ».

Variables d'environnement : API_PORT, API_HOST, DESCRIPTOR_API_KEY (si défini, l'en-tête
« X-API-Key » devient obligatoire sauf pour /api/health), API_MAX_FILES, MAX_CONTENT_LENGTH.
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):                        # lancé directement : « python api/app.py »
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, request                       # noqa: E402
from flask_restful import Api, Resource                         # noqa: E402
from PIL import Image                                           # noqa: E402

from api import descriptors                                     # noqa: E402

__version__ = "2.0.0"
PUBLIC_ENDPOINTS = {"health"}                         # accessibles sans clé d'API


def create_app(**overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 512 * 1024 * 1024)),
        API_KEY=os.environ.get("DESCRIPTOR_API_KEY", ""),
        MAX_FILES=int(os.environ.get("API_MAX_FILES", 64)),      # images par requête
        MAX_IMAGE_PIXELS=50_000_000,
        PROPAGATE_EXCEPTIONS=False,
    )
    app.config.update(overrides)
    Image.MAX_IMAGE_PIXELS = app.config["MAX_IMAGE_PIXELS"]      # refuse les bombes de décompression
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    api = Api(app, catch_all_404s=True)

    @app.before_request
    def require_api_key():
        key = app.config["API_KEY"]
        if key and request.endpoint not in PUBLIC_ENDPOINTS:
            sent = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(sent.encode(), key.encode()):
                return jsonify(error="Clé d'API absente ou invalide (en-tête X-API-Key)."), 401

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify(error="Requête trop volumineuse."), 413

    class Health(Resource):
        def get(self):
            return {"status": "ok", "version": __version__, "vector_dim": descriptors.VECTOR_DIM}

    class Info(Resource):
        def get(self):
            return {"vector_dim": descriptors.VECTOR_DIM,
                    "layout": [{"name": n, "size": s} for n, s in descriptors.LAYOUT],
                    "parameters": {"max_side_px": descriptors.MAX_SIDE,
                                   "hsv_bins": [descriptors.H_BINS, descriptors.S_BINS, descriptors.V_BINS],
                                   "glcm": {"levels": descriptors.GLCM_LEVELS, "distance": 1,
                                            "angles_deg": [0, 45, 90, 135],
                                            "properties": descriptors.GLCM_PROPS + ["entropy"]},
                                   "lbp": {"P": descriptors.LBP_P, "R": descriptors.LBP_R, "method": "uniform"},
                                   "dominant_colors": descriptors.N_DOMINANT},
                    "limits": {"max_files_per_request": app.config["MAX_FILES"]}}

    class DescriptorResource(Resource):
        """Classe de base : factorise lecture des fichiers, boucle sur le lot et gestion d'erreurs.
        Les sous-classes ne définissent que la fonction de calcul (`compute`)."""
        compute = None

        def post(self):
            files = request.files.getlist("images")
            if not files:
                return {"error": "Aucun fichier reçu (champ multipart 'images' attendu)."}, 400
            if len(files) > app.config["MAX_FILES"]:
                return {"error": f"Trop d'images ({len(files)} > {app.config['MAX_FILES']} par requête)."}, 413
            results = []
            for f in files:
                try:
                    results.append({"filename": f.filename, **self.compute(f.stream)})
                except Exception as exc:                  # image corrompue, format inconnu...
                    app.logger.info("Image rejetée (%s) : %s", f.filename, exc)
                    results.append({"filename": f.filename, "error": f"Image illisible : {exc}"})
            return {"count": len(results), "results": results}, 200

    class AllDescriptors(DescriptorResource):
        compute = staticmethod(descriptors.compute_all)

    class ColorDescriptors(DescriptorResource):
        compute = staticmethod(descriptors.compute_color)

    class TextureDescriptors(DescriptorResource):
        compute = staticmethod(descriptors.compute_texture)

    api.add_resource(Health, "/api/health", endpoint="health")
    api.add_resource(Info, "/api/descriptors/info", endpoint="info")
    api.add_resource(AllDescriptors, "/api/descriptors", endpoint="all")
    api.add_resource(ColorDescriptors, "/api/descriptors/color", endpoint="color")
    api.add_resource(TextureDescriptors, "/api/descriptors/texture", endpoint="texture")
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("API_HOST", "127.0.0.1"), port=int(os.environ.get("API_PORT", 5001)), debug=False)
