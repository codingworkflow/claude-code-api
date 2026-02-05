#!/usr/bin/env python3
"""
OAuth Callback Proxy for Claude Code in Docker

This proxy runs on the host machine and forwards OAuth callbacks from MCP servers
into the Docker container where Claude Code is running.

Usage:
    python3 docker/oauth-proxy.py [--port PORT] [--container-host HOST]

The proxy listens for OAuth callbacks on the host and forwards them to the container.
"""

import asyncio
import argparse
import logging
import sys
from typing import Dict, Any
from urllib.parse import urlencode, parse_qs, urlparse

try:
    from aiohttp import web, ClientSession, ClientError
except ImportError:
    print("Error: aiohttp is required. Install with: pip install aiohttp")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('oauth-proxy')


class OAuthProxy:
    """OAuth callback proxy for Docker containers."""

    def __init__(self, container_host: str = "localhost", container_port: int = 8000):
        self.container_host = container_host
        self.container_port = container_port
        self.active_sessions: Dict[str, int] = {}  # session_id -> callback_port mapping

    async def handle_oauth_callback(self, request: web.Request) -> web.Response:
        """Handle OAuth callback and forward to container."""
        try:
            # Get all query parameters
            query_params = dict(request.query)

            logger.info(f"Received OAuth callback: {request.url}")
            logger.info(f"Query params: {query_params}")

            # Extract session info if provided
            session_id = query_params.get('state', 'unknown')
            callback_port = query_params.get('callback_port')

            if not callback_port:
                # Try to determine callback port from state or other params
                logger.warning("No callback_port specified, using default container port")
                callback_port = self.container_port
            else:
                callback_port = int(callback_port)

            # Forward to container
            target_url = f"http://{self.container_host}:{callback_port}/oauth/callback"

            logger.info(f"Forwarding OAuth callback to: {target_url}")

            async with ClientSession() as session:
                try:
                    # Forward the callback with all query parameters
                    async with session.get(target_url, params=query_params, timeout=10) as resp:
                        response_text = await resp.text()

                        logger.info(f"Container response: {resp.status}")

                        # Return success page to user
                        return web.Response(
                            text=self._success_html(session_id),
                            content_type='text/html',
                            status=200
                        )

                except ClientError as e:
                    logger.error(f"Failed to forward to container: {e}")
                    return web.Response(
                        text=self._error_html(str(e)),
                        content_type='text/html',
                        status=502
                    )

        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}", exc_info=True)
            return web.Response(
                text=self._error_html(str(e)),
                content_type='text/html',
                status=500
            )

    async def handle_register_callback(self, request: web.Request) -> web.Response:
        """Register a callback port for a session."""
        try:
            data = await request.json()
            session_id = data.get('session_id')
            callback_port = data.get('callback_port')

            if not session_id or not callback_port:
                return web.json_response(
                    {'error': 'Missing session_id or callback_port'},
                    status=400
                )

            self.active_sessions[session_id] = int(callback_port)

            logger.info(f"Registered callback for session {session_id} on port {callback_port}")

            return web.json_response({
                'status': 'registered',
                'session_id': session_id,
                'callback_url': f'http://localhost:{self.proxy_port}/oauth/callback?state={session_id}&callback_port={callback_port}'
            })

        except Exception as e:
            logger.error(f"Error registering callback: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            'status': 'healthy',
            'service': 'oauth-proxy',
            'container_host': self.container_host,
            'container_port': self.container_port,
            'active_sessions': len(self.active_sessions)
        })

    def _success_html(self, session_id: str) -> str:
        """Generate success HTML page."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>OAuth Authentication Successful</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
        }}
        h1 {{
            color: #333;
            margin-bottom: 20px;
        }}
        .checkmark {{
            font-size: 64px;
            color: #4CAF50;
            margin-bottom: 20px;
        }}
        p {{
            color: #666;
            line-height: 1.6;
        }}
        .session {{
            background: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="checkmark">✓</div>
        <h1>Authentication Successful!</h1>
        <p>Your MCP server has been successfully authenticated with Claude Code.</p>
        <p>You can now close this window and return to your terminal.</p>
        <div class="session">Session: {session_id}</div>
    </div>
</body>
</html>
"""

    def _error_html(self, error: str) -> str:
        """Generate error HTML page."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>OAuth Authentication Failed</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
        }}
        h1 {{
            color: #333;
            margin-bottom: 20px;
        }}
        .error-icon {{
            font-size: 64px;
            color: #f44336;
            margin-bottom: 20px;
        }}
        p {{
            color: #666;
            line-height: 1.6;
        }}
        .error {{
            background: #ffebee;
            padding: 10px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 12px;
            margin-top: 20px;
            color: #c62828;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">✗</div>
        <h1>Authentication Failed</h1>
        <p>There was an error completing the OAuth authentication.</p>
        <p>Please try again or check the logs for more details.</p>
        <div class="error">{error}</div>
    </div>
</body>
</html>
"""


async def create_app(proxy: OAuthProxy, port: int) -> web.Application:
    """Create and configure the web application."""
    app = web.Application()

    # Store proxy port for callback URL generation
    proxy.proxy_port = port

    # Add routes
    app.router.add_get('/oauth/callback', proxy.handle_oauth_callback)
    app.router.add_post('/oauth/register', proxy.handle_register_callback)
    app.router.add_get('/health', proxy.handle_health)

    # Root endpoint with instructions
    async def handle_root(request):
        return web.Response(
            text="""
<!DOCTYPE html>
<html>
<head>
    <title>OAuth Proxy for Claude Code</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 { color: #333; }
        pre {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
        .info { background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0; }
    </style>
</head>
<body>
    <h1>OAuth Proxy for Claude Code</h1>
    <div class="info">
        <strong>Status:</strong> Running<br>
        <strong>Callback URL:</strong> <code>http://localhost:""" + str(port) + """/oauth/callback</code>
    </div>
    <h2>Usage</h2>
    <p>This proxy forwards OAuth callbacks from MCP servers into your Docker container.</p>
    <h3>Endpoints:</h3>
    <ul>
        <li><code>/oauth/callback</code> - OAuth callback handler</li>
        <li><code>/oauth/register</code> - Register a callback port (POST)</li>
        <li><code>/health</code> - Health check</li>
    </ul>
</body>
</html>
""",
            content_type='text/html'
        )

    app.router.add_get('/', handle_root)

    return app


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='OAuth Callback Proxy for Claude Code in Docker'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8888,
        help='Port to listen on for OAuth callbacks (default: 8888)'
    )
    parser.add_argument(
        '--container-host',
        default='localhost',
        help='Container host (default: localhost)'
    )
    parser.add_argument(
        '--container-port',
        type=int,
        default=8000,
        help='Container port (default: 8000)'
    )

    args = parser.parse_args()

    # Create proxy
    proxy = OAuthProxy(
        container_host=args.container_host,
        container_port=args.container_port
    )

    # Create and run app
    logger.info(f"Starting OAuth Proxy on port {args.port}")
    logger.info(f"Forwarding to container at {args.container_host}:{args.container_port}")
    logger.info(f"OAuth callback URL: http://localhost:{args.port}/oauth/callback")
    logger.info("Press Ctrl+C to stop")

    app = asyncio.run(create_app(proxy, args.port))
    web.run_app(app, host='0.0.0.0', port=args.port)


if __name__ == '__main__':
    main()
