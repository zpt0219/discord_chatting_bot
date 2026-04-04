"""
Tunnel Server - Runs on the REMOTE server (adna.world)

Creates two services:
1. HTTP proxy on port 8888 - intercepts requests meant for the local Llama model
2. WebSocket relay on port 9999 - maintains a persistent connection to the tunnel client

When the bot calls http://127.0.0.1:8888/v1/..., this server catches the request,
forwards it through the WebSocket tunnel to the client on your local PC,
which then forwards it to the real Llama server.

Usage:
    python tunnel_server.py

Environment variables (.env):
    TUNNEL_SECRET  - shared secret for authenticating tunnel clients
    TUNNEL_WS_PORT - WebSocket relay port (default: 9999)
    TUNNEL_HTTP_PORT - HTTP proxy port (default: 8888)
"""

import os
import json
import uuid
import asyncio
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

TUNNEL_SECRET = os.environ.get("TUNNEL_SECRET", "change_me_please")
WS_PORT = int(os.environ.get("TUNNEL_WS_PORT", "9999"))
HTTP_PORT = int(os.environ.get("TUNNEL_HTTP_PORT", "8888"))

# =========================================================
# STATE: Track the connected tunnel client
# =========================================================

class TunnelState:
    """Holds the WebSocket connection to the tunnel client and pending request futures."""
    def __init__(self):
        self.client_ws = None                  # The WebSocket connection to the tunnel client
        self.pending_requests: dict = {}       # {request_id: asyncio.Future}
        self.lock = asyncio.Lock()

tunnel = TunnelState()

# =========================================================
# WEBSOCKET RELAY (port 9999)
# =========================================================

async def ws_handler(request):
    """Handles incoming WebSocket connections from tunnel clients."""
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    
    # Step 1: Authenticate the client
    try:
        auth_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
        if auth_msg.get("type") != "auth" or auth_msg.get("secret") != TUNNEL_SECRET:
            await ws.send_json({"type": "auth_fail", "error": "Invalid secret"})
            await ws.close()
            return ws
    except (asyncio.TimeoutError, Exception) as e:
        print(f"[TUNNEL] Auth failed: {e}")
        await ws.close()
        return ws
    
    # Step 2: Accept the connection
    async with tunnel.lock:
        if tunnel.client_ws and not tunnel.client_ws.closed:
            # Disconnect old client
            await tunnel.client_ws.close()
        tunnel.client_ws = ws
    
    await ws.send_json({"type": "auth_ok"})
    print(f"[TUNNEL] Client connected from {request.remote}")
    
    # Step 3: Listen for responses from the client
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    req_id = data.get("id")
                    if data.get("type") == "response" and req_id in tunnel.pending_requests:
                        tunnel.pending_requests[req_id].set_result(data)
                    elif data.get("type") == "heartbeat":
                        await ws.send_json({"type": "heartbeat_ack"})
                except json.JSONDecodeError:
                    pass
            elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    except Exception as e:
        print(f"[TUNNEL] Client connection error: {e}")
    finally:
        async with tunnel.lock:
            if tunnel.client_ws is ws:
                tunnel.client_ws = None
        # Cancel all pending requests so they fail fast
        for req_id, future in tunnel.pending_requests.items():
            if not future.done():
                future.set_exception(Exception("Tunnel client disconnected"))
        tunnel.pending_requests.clear()
        print(f"[TUNNEL] Client disconnected")
    
    return ws

# =========================================================
# HTTP PROXY (port 8888) - pretends to be the Llama server
# =========================================================

async def proxy_handler(request: web.Request):
    """
    Catches all HTTP requests to port 8888 (where the bot thinks Llama is),
    serializes them, and forwards through the WebSocket tunnel to the client.
    """
    # Check if tunnel client is connected
    if not tunnel.client_ws or tunnel.client_ws.closed:
        return web.json_response(
            {"error": "Local model tunnel is not connected"},
            status=503
        )
    
    # Read the full request body
    body = await request.read()
    
    # Create a unique request ID
    req_id = str(uuid.uuid4())
    
    # Serialize the request
    forwarded = {
        "type": "request",
        "id": req_id,
        "method": request.method,
        "path": request.path_qs,  # includes query string
        "headers": dict(request.headers),
        "body": body.decode("utf-8", errors="replace")
    }
    
    # Create a future to wait for the response
    future = asyncio.get_event_loop().create_future()
    tunnel.pending_requests[req_id] = future
    
    try:
        # Send through the WebSocket
        await tunnel.client_ws.send_json(forwarded)
        
        # Wait for the response (with timeout)
        response_data = await asyncio.wait_for(future, timeout=300.0)
        
        # Reconstruct the HTTP response
        status = response_data.get("status", 500)
        resp_headers = response_data.get("headers", {})
        resp_body = response_data.get("body", "")
        
        return web.Response(
            status=status,
            body=resp_body.encode("utf-8"),
            content_type=resp_headers.get("Content-Type", "application/json")
        )
    except asyncio.TimeoutError:
        return web.json_response({"error": "Tunnel request timed out"}, status=504)
    except Exception as e:
        return web.json_response({"error": f"Tunnel error: {str(e)}"}, status=502)
    finally:
        tunnel.pending_requests.pop(req_id, None)

# =========================================================
# STATUS ENDPOINT
# =========================================================

async def status_handler(request):
    """Quick health check endpoint."""
    connected = tunnel.client_ws is not None and not tunnel.client_ws.closed
    return web.json_response({
        "tunnel_connected": connected,
        "pending_requests": len(tunnel.pending_requests)
    })

# =========================================================
# MAIN
# =========================================================

async def start_servers():
    """Start both the WebSocket relay and HTTP proxy servers."""
    
    # --- WebSocket relay app (port 9999) ---
    ws_app = web.Application()
    ws_app.router.add_get("/ws", ws_handler)
    ws_app.router.add_get("/status", status_handler)
    
    ws_runner = web.AppRunner(ws_app)
    await ws_runner.setup()
    ws_site = web.TCPSite(ws_runner, "0.0.0.0", WS_PORT)
    await ws_site.start()
    print(f"[TUNNEL] WebSocket relay listening on 0.0.0.0:{WS_PORT}")
    
    # --- HTTP proxy app (port 8888) ---
    http_app = web.Application()
    # Catch ALL routes and methods
    http_app.router.add_route("*", "/{path:.*}", proxy_handler)
    
    http_runner = web.AppRunner(http_app)
    await http_runner.setup()
    http_site = web.TCPSite(http_runner, "127.0.0.1", HTTP_PORT)
    await http_site.start()
    print(f"[TUNNEL] HTTP proxy listening on 127.0.0.1:{HTTP_PORT}")
    
    print(f"[TUNNEL] Server ready! Waiting for tunnel client to connect...")
    print(f"[TUNNEL] Bot will use http://127.0.0.1:{HTTP_PORT}/v1 as LOCAL_LLAMA_BASE_URL")
    
    # Keep running forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    print("=" * 60)
    print("  TUNNEL SERVER - Run this on the REMOTE server")
    print("=" * 60)
    asyncio.run(start_servers())
