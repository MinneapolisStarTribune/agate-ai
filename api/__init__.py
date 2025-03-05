import os
from flask import Flask

def create_app(script_info=None):
    # instantiate the app
    app = Flask(
        __name__
    )

    # set config
    app_settings = os.getenv("APP_SETTINGS")
    app.config.from_object(app_settings)

    # register blueprints
    from api.app import main_blueprint

    app.register_blueprint(main_blueprint)

    # shell context for flask cli
    app.shell_context_processor({"app": app})

    return app