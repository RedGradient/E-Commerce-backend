import os

# Load test settings from .env.test when app.config.Settings is imported.
os.environ.setdefault("ENV_FILE", ".env.test")
