module.exports = {
  apps: [
    {
      name: "movie-stream-backend",
      script: "python3",
      args: "-m Backend",
      cwd: "./",
      interpreter: "none",
      restart_delay: 3000,
      autorestart: true,
      max_restarts: 10,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
