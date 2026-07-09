#!/usr/bin/env python3
"""
Notepad REST server — HTTP surface for ~/.maestro/blackboards/
Agents read/write shared state programmatically via HTTP.
"""
from aiohttp import web
import json, pathlib, asyncio

BB_ROOT = pathlib.Path("/home/andjesse/.maestro/blackboards")
PORT = 8651

routes = web.RouteTableDef()

def _board_path(board: str) -> pathlib.Path:
    clean = "".join(c for c in board if c.isalnum() or c in "-_")
    return BB_ROOT / f"{clean}.json"

@routes.get("/np")
async def list_boards(req):
    boards = [p.stem for p in BB_ROOT.glob("*.json") if not p.stem.startswith("backup")]
    return web.json_response({"boards": boards})

@routes.get("/np/{board}")
async def read_board(req):
    p = _board_path(req.match_info["board"])
    if not p.exists():
        return web.json_response({})
    return web.json_response(json.loads(p.read_text()))

@routes.post("/np/{board}")
async def write_board(req):
    p = _board_path(req.match_info["board"])
    body = await req.json()
    existing = json.loads(p.read_text()) if p.exists() else {}
    if isinstance(existing, dict) and isinstance(body, dict):
        existing.update(body)
        data = existing
    else:
        data = body
    p.write_text(json.dumps(data, indent=2))
    return web.json_response({"ok": True})

@routes.get("/np/{board}/search")
async def search_board(req):
    p = _board_path(req.match_info["board"])
    q = req.rel_url.query.get("q", "").lower()
    if not p.exists():
        return web.json_response({"results": []})
    data = json.loads(p.read_text())
    results = []
    for k, v in (data.items() if isinstance(data, dict) else []):
        if q in k.lower() or q in json.dumps(v).lower():
            results.append({"key": k, "value": v})
    return web.json_response({"results": results})

@routes.delete("/np/{board}/{key}")
async def delete_key(req):
    p = _board_path(req.match_info["board"])
    key = req.match_info["key"]
    if p.exists():
        data = json.loads(p.read_text())
        if isinstance(data, dict) and key in data:
            del data[key]
            p.write_text(json.dumps(data, indent=2))
    return web.json_response({"ok": True})

if __name__ == "__main__":
    app = web.Application()
    app.add_routes(routes)
    print(f"Notepad server on http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)
