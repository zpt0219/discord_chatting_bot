"""
Tunnel Client - Runs on your LOCAL PC

Connects to the tunnel server on adna.world via WebSocket.
When the remote bot sends an LLM request, this client receives it,
forwards it to the real local Llama server at 127.0.0.1:8888,
and sends the response back through the tunnel.

Usage:
    python tunnel_client.py

Environment variables (.env):
    TUNNEL_SECRET      - shared secret (must match the server)
    TUNNEL_SERVER_URL  - WebSocket URL of the tunnel server (default: ws://adna.world:9999/ws)
    LOCAL_LLAMA_URL    - Local Llama server URL (default: http://127.0.0.1:8888)
"""

import os
import json
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

TUNNEL_SECRET = os.environ.get("TUNNEL_SECRET", "change_me_please")
TUNNEL_SERVER_URL = os.environ.get("TUNNEL_SERVER_URL", "ws://adna.world:9999/ws")
LOCAL_LLAMA_URL = os.environ.get("LOCAL_LLAMA_URL", "http://127.0.0.1:8888")

# =========================================================
# FORWARDING LOGIC
# =========================================================

async def forward_to_local_llama(session: aiohttp.ClientSession, request_data: dict) -> dict:
    """
    Takes a serialized HTTP request from the tunnel server,
    replays it against the real local Llama server,
    and returns the serialized response.
    """
    method = request_data.get("method", "POST")
    path = request_data.get("path", "/")
    headers = request_data.get("headers", {})
    body = request_data.get("body", "")
    
    # Build the full URL to the local Llama server
    url = f"{LOCAL_LLAMA_URL}{path}"
    
    # Strip hop-by-hop headers that shouldn't be forwarded
    skip_headers = {"host", "transfer-encoding", "connection", "upgrade"}
    clean_headers = {k: v for k, v in headers.items() if k.lower() not in skip_headers}
    
    try:
        async with session.request(
            method=method,
            url=url,
            headers=clean_headers,
            data=body.encode("utf-8") if body else None,
            timeout=aiohttp.ClientTimeout(total=300)
        ) as resp:
            resp_body = await resp.text()
            resp_headers = dict(resp.headers)
            
            return {
                "type": "response",
                "id": request_data["id"],
                "status": resp.status,
                "headers": {k: v for k, v in resp_headers.items() 
                           if k.lower() not in skip_headers},
                "body": resp_body
            }
    except aiohttp.ClientConnectorError:
        return {
            "type": "response",
            "id": request_data["id"],
            "status": 503,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Local Llama server is not running on " + LOCAL_LLAMA_URL})
        }
    except asyncio.TimeoutError:
        return {
            "type": "response",
            "id": request_data["id"],
            "status": 504,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Local Llama server timed out"})
        }
    except Exception as e:
        return {
            "type": "response",
            "id": request_data["id"],
            "status": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Forward error: {str(e)}"})
        }

# =========================================================
# HEARTBEAT
# =========================================================

async def heartbeat_loop(ws):
    """Sends periodic heartbeats to keep the connection alive."""
    try:
        while True:
            await asyncio.sleep(25)
            await ws.send_json({"type": "heartbeat"})
    except Exception:
        pass  # Connection died, will be handled by the main loop

# =========================================================
# MAIN CONNECTION LOOP (with auto-reconnect)
# =========================================================

async def run_client():
    """Main loop that connects to the tunnel server and handles requests."""
    
    reconnect_delay = 2  # Start with 2 seconds
    max_delay = 60       # Cap at 60 seconds
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                print(f"[TUNNEL CLIENT] Connecting to {TUNNEL_SERVER_URL}...")
                
                async with session.ws_connect(
                    TUNNEL_SERVER_URL,
                    heartbeat=30.0,
                    timeout=10.0
                ) as ws:
                    # Step 1: Authenticate
                    await ws.send_json({"type": "auth", "secret": TUNNEL_SECRET})
                    
                    auth_resp = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
                    if auth_resp.get("type") != "auth_ok":
                        print(f"[TUNNEL CLIENT] Authentication failed: {auth_resp.get('error', 'unknown')}")
                        await asyncio.sleep(reconnect_delay)
                        continue
                    
                    print(f"[TUNNEL CLIENT] Connected and authenticated!")
                    print(f"[TUNNEL CLIENT] Forwarding requests to {LOCAL_LLAMA_URL}")
                    reconnect_delay = 2  # Reset backoff on successful connection
                    
                    # Start heartbeat in background
                    heartbeat_task = asyncio.create_task(heartbeat_loop(ws))
                    
                    # Step 2: Process incoming requests
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    
                                    if data.get("type") == "request":
                                        # Forward the request to local Llama
                                        req_id = data.get("id", "?")
                                        method = data.get("method", "?")
                                        path = data.get("path", "?")
                                        print(f"[TUNNEL CLIENT] → {method} {path} (id: {req_id[:8]}...)")
                                        
                                        response = await forward_to_local_llama(session, data)
                                        await ws.send_json(response)
                                        
                                        print(f"[TUNNEL CLIENT] ← {response['status']} (id: {req_id[:8]}...)")
                                    
                                    elif data.get("type") == "heartbeat_ack":
                                        pass  # Heartbeat acknowledged
                                        
                                except json.JSONDecodeError:
                                    pass
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                                break
                    finally:
                        heartbeat_task.cancel()
                        
            except aiohttp.ClientConnectorError:
                print(f"[TUNNEL CLIENT] Cannot reach server at {TUNNEL_SERVER_URL}")
            except asyncio.TimeoutError:
                print(f"[TUNNEL CLIENT] Connection timed out")
            except Exception as e:
                print(f"[TUNNEL CLIENT] Connection error: {e}")
            
            print(f"[TUNNEL CLIENT] Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_delay)

if __name__ == "__main__":
    print("=" * 60)
    print("  TUNNEL CLIENT - Run this on your LOCAL PC")
    print(f"  Server:  {TUNNEL_SERVER_URL}")
    print(f"  Llama:   {LOCAL_LLAMA_URL}")
    print("=" * 60)
    asyncio.run(run_client())
