from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
APP_DIR = BASE_DIR / "app" / "stock_mvp"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

DB_PATH = DATA_DIR / "stock_mvp.db"
RULES_PATH = CONFIG_DIR / "rules.yaml"
SAMPLE_STOCKS_PATH = DATA_DIR / "sample_stocks.csv"
SAMPLE_EVENTS_PATH = DATA_DIR / "sample_events.csv"
