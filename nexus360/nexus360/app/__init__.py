from flask import Flask
from config import Config

# Each module is a Flask Blueprint living in app/modules/<name>/routes.py
MODULES = [
    ("auth",         "app.modules.auth.routes",         ""),
    ("dashboard",    "app.modules.dashboard.routes",    "/dashboard"),
    ("cims",         "app.modules.cims.routes",         "/cims"),
    ("pipeline",     "app.modules.pipeline.routes",     "/pipeline"),
    ("journey",      "app.modules.journey.routes",      "/journey"),
    ("vsi",          "app.modules.vsi.routes",          "/vsi"),
    ("crosssell",     "app.modules.crosssell.routes",    "/crosssell"),
    ("contracts",    "app.modules.contracts.routes",    "/contracts"),
    ("integrations", "app.modules.integrations.routes", "/integrations"),
]


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from app import db
    db.init_app(app)

    import importlib
    for _name, path, prefix in MODULES:
        mod = importlib.import_module(path)
        app.register_blueprint(mod.bp, url_prefix=prefix)

    @app.route("/")
    def home():
        from flask import redirect, url_for
        return redirect(url_for("dashboard.index"))

    return app
