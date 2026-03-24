---
title: Project Stream
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# 🎥 Project Stream - FastAPI & Telegram Bot

This is a high-performance Telegram bot built with **Pyrogram (Pyrofork)** and **FastAPI**, deployed on Hugging Face Spaces.

## 🛠 Features
- **FastAPI Backend**: Handles web requests and health checks.
- **Telegram Bot**: Processes file requests and user management.
- **24/7 Hosting**: Runs on Hugging Face's Free CPU tier.
- **Database**: Integrated with MongoDB.

## 🚀 Deployment Details
- **SDK**: Docker
- **Port**: 7860 (Hugging Face Default)
- **Runtime**: Python 3.10-slim

## 🚀 Deployment Notes
- **Port**: Must listen on port `7860`.
- **Environment**: Runs inside a Docker container.
- **Secrets**: API_ID, API_HASH, and BOT_TOKEN are managed via Hugging Face Space Secrets.

## 📂 Project Structure
- `Backend/`: Main application logic.
- `Dockerfile`: Container configuration.
- `requirements.txt`: Python dependencies.

---
*Note: This Space runs 24/7 on the Free CPU tier. Ensure `in_memory=True` is used in Pyrogram to handle the read-only filesystem.*
*Developed with ❤️ for ThiruEmpire.*
