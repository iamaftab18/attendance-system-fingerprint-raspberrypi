from flask_sqlalchemy import SQLAlchemy


# Shared Flask extensions live here so models and routes do not need to import
# the Flask application object. This prevents circular imports during startup.
db = SQLAlchemy()
