from __future__ import annotations

from dotenv import load_dotenv

from app.stock_mvp.core import db
from app.stock_mvp.services.pipeline import PipelineService

load_dotenv()


def main() -> None:
    db.init_db()
    payload = PipelineService().run_scan(run_type="cli_manual")
    run = payload["run"]
    recs = payload["recommendations"]
    print(f"Run #{run['id']} completed with {len(recs)} recommendations")
    for r in recs[:5]:
        print(f"{r['rank']}. {r['symbol']} score={r['final_score']}")


if __name__ == "__main__":
    main()
