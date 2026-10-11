from Backend.config import Telegram
import uvicorn
from Backend.fastapi.main import app

# Fetch host and port from the Telegram configuration
Port = Telegram.PORT

# Set up Uvicorn configuration with the specified host and port (with reverse proxy support)
config = uvicorn.Config(
    app=app,
    host='0.0.0.0',
    port=Port,
    proxy_headers=True,
    forwarded_allow_ips='*'
)
server = uvicorn.Server(config)
