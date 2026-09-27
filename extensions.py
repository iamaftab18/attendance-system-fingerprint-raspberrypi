from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail


# Shared Flask extensions live here so models and routes do not need to import
# the Flask application object. This prevents circular imports during startup.
db = SQLAlchemy()
mail = Mail()
