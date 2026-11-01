"""Standalone relay: imports neither NoneBot plugins nor the bot's database."""
import argparse
import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from arcade_helper.web.protocol import MAX_PACKET
from arcade_helper.web.relay import create_app as editor_app


def create_app(*, token, public_url):
    app = editor_app(token=token, public_url=public_url)
    directory = Path(__file__).resolve().parents[1] / "web" / "management"

    @app.get("/manage/clanbattle/")
    @app.get("/manage/aliases/")
    async def module_page():
        return FileResponse(directory / "index.html", media_type="text/html")

    app.mount("/manage", StaticFiles(directory=directory, html=True))
    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description="DreamRain management relay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app(token=os.environ.get("ARCADE_RELAY_TOKEN"), public_url=os.environ.get("ARCADE_RELAY_ORIGIN", f"http://127.0.0.1:{args.port}"))
    uvicorn.run(app, host=args.host, port=args.port, ws_max_size=MAX_PACKET,
                forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))
