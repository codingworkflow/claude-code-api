# Docker OAuth Setup for MCP Servers

This guide explains how to authenticate MCP servers that require OAuth when running Claude Code inside a Docker container.

## The Problem

MCP servers (like GitHub, Gmail, etc.) use OAuth authentication which requires:
1. Opening a browser to authenticate
2. Redirecting back to `http://localhost:[random-port]/callback`

**Issue**: The Docker container can't receive these callbacks because:
- The browser runs on your host machine
- The callback URL points to `localhost` on the host
- The Docker container has a different network namespace

## The Solution: OAuth Proxy

We've created an OAuth proxy that runs on your host machine and forwards callbacks into the container.

## Setup Instructions

### Step 1: Install Dependencies

The OAuth proxy requires `aiohttp`:

```bash
pip install aiohttp
```

Or if using the project virtualenv:

```bash
cd claude-code-api
pip install -e .
pip install aiohttp
```

### Step 2: Start the OAuth Proxy

In a **separate terminal** (keep it running), start the OAuth proxy:

```bash
python3 docker/oauth-proxy.py
```

You should see:
```
Starting OAuth Proxy on port 8888
Forwarding to container at localhost:8000
OAuth callback URL: http://localhost:8888/oauth/callback
Press Ctrl+C to stop
```

**Optional**: Run on a different port:
```bash
python3 docker/oauth-proxy.py --port 9999
```

### Step 3: Start Docker Container

In your main terminal:

```bash
docker-compose -f docker/docker-compose.yml up -d
```

This compose file mounts your host Claude auth directory:

- `${HOME}/.claude` → `/home/claudeuser/.claude`

Ensure your host `~/.claude` contains your Claude Code/Max auth before starting.

### Step 4: Configure MCP Servers

When configuring MCP servers that require OAuth, you'll need to set the callback URL to use the proxy.

#### Option A: During Interactive Authentication

1. Run `claude` inside the container:
   ```bash
   docker exec -it claude-code-api claude
   ```

2. When Claude prompts you to authenticate an MCP server:
   - Copy the authentication URL
   - Open it in your **host** browser (not container)
   - Complete the OAuth flow
   - The callback will automatically be forwarded through the proxy

#### Option B: Manual Configuration

If you need to manually configure callback URLs in MCP server settings:

**Use**: `http://localhost:8888/oauth/callback`

Instead of the default random port that Claude Code generates.

### Step 5: Verify Setup

Check that both services are running:

```bash
# Check API server
curl http://localhost:8000/health

# Check OAuth proxy
curl http://localhost:8888/health
```

Both should return healthy status.

## How It Works

```
┌─────────────────┐
│  Your Browser   │
│   (on host)     │
└────────┬────────┘
         │ 1. OAuth redirect
         │    http://localhost:8888/oauth/callback?code=...
         ▼
┌─────────────────┐
│  OAuth Proxy    │
│   (on host)     │  Runs: docker/oauth-proxy.py
│   Port: 8888    │
└────────┬────────┘
         │ 2. Forward callback
         │    http://localhost:8000/...
         ▼
┌─────────────────┐
│ Docker Container│
│  Claude Code    │  Receives callback
│   Port: 8000    │  Completes auth
└─────────────────┘
```

## Troubleshooting

### Issue: "Connection refused" when forwarding callback

**Solution**: Make sure the Docker container is running:
```bash
docker ps | grep claude-code-api
```

### Issue: OAuth proxy can't reach container

**Solution**: Check that port 8888 is exposed in `docker/docker-compose.yml`:
```yaml
ports:
  - "127.0.0.1:8000:8000"
  - "127.0.0.1:8888:8888"  # Should be present
```

### Issue: Browser shows "localhost:8888 refused to connect"

**Solution**: OAuth proxy isn't running. Start it in a separate terminal:
```bash
python3 docker/oauth-proxy.py
```

### Issue: Callback succeeds but MCP still not authenticated

**Solution**: Check container logs:
```bash
docker logs claude-code-api
```

Look for errors in the OAuth flow.

## Advanced Configuration

### Custom Container Host

If running Docker on a different machine:

```bash
python3 docker/oauth-proxy.py --container-host 192.168.1.100 --container-port 8000
```

### Multiple Containers

Run multiple proxies on different ports:

```bash
# Terminal 1 - Container 1
python3 docker/oauth-proxy.py --port 8888 --container-port 8000

# Terminal 2 - Container 2
python3 docker/oauth-proxy.py --port 8889 --container-port 8001
```

### Production Deployment

For production, run the OAuth proxy as a systemd service:

1. Create `/etc/systemd/system/claude-oauth-proxy.service`:

```ini
[Unit]
Description=OAuth Proxy for Claude Code
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/claude-code-api
ExecStart=/usr/bin/python3 /path/to/claude-code-api/docker/oauth-proxy.py
Restart=always

[Install]
WantedBy=multi-user.target
```

2. Enable and start:

```bash
sudo systemctl enable claude-oauth-proxy
sudo systemctl start claude-oauth-proxy
```

## Alternative: Host Network Mode (Linux/Mac Only)

If you're on Linux or Mac, you can use host network mode instead of the proxy:

Edit `docker/docker-compose.yml`:

```yaml
services:
  claude-code-api:
    network_mode: "host"
    # Remove 'ports' section when using host mode
```

**Pros**: No proxy needed, simpler setup
**Cons**: Less isolation, Linux/Mac only, not recommended for production

## Security Notes

1. The OAuth proxy only forwards callbacks, it doesn't store credentials
2. All communication is local (localhost only by default)
3. For production, consider:
   - Adding authentication to the proxy
   - Using HTTPS
   - Restricting which containers can be targeted
   - Running behind a reverse proxy

## Testing the Setup

Test the complete flow:

```bash
# 1. Start OAuth proxy
python3 docker/oauth-proxy.py

# 2. In another terminal, start container
docker-compose -f docker/docker-compose.yml up -d

# 3. Test callback forwarding
curl "http://localhost:8888/oauth/callback?code=test123&state=test-session"

# Should return a success page
```

## Support

If you encounter issues:

1. Check all services are running:
   - OAuth proxy: `curl http://localhost:8888/health`
   - API server: `curl http://localhost:8000/health`
   - Container: `docker ps`

2. Check logs:
   ```bash
   # OAuth proxy logs (in terminal where it's running)
   # Container logs
   docker logs claude-code-api
   ```

3. Verify network connectivity:
   ```bash
   # From host to container
   curl http://localhost:8000/health
   ```

## FAQ

**Q: Do I need to run the OAuth proxy all the time?**
A: Only when authenticating MCP servers. Once authenticated, credentials are stored and the proxy isn't needed.

**Q: Can I use this with existing authenticated MCP servers?**
A: Yes! If you already authenticated MCP servers on your host, just mount your `~/.config/claude` directory:
```yaml
volumes:
  - ~/.config/claude:/home/claudeuser/.config/claude
```

**Q: Does this work on Windows?**
A: Yes! The OAuth proxy runs on any platform. Just use `python` instead of `python3` on Windows.

**Q: How do I stop everything?**
A:
```bash
# Stop OAuth proxy: Ctrl+C in its terminal
# Stop container
docker-compose -f docker/docker-compose.yml down
```
