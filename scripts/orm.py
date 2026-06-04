import sys
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.bootstrap import init_nonebot_app


def main():
    init_nonebot_app()

    from nonebot_plugin_orm.__main__ import main as orm_main

    orm_main(args=sys.argv[1:] or ["check"], prog_name="orm")


if __name__ == "__main__":
    main()
