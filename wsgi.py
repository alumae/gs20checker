"""Vercel's Flask entry point; the local CLI continues to use the factory."""

from app import create_app

app = create_app()
