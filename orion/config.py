"""
Configuration — load environment variables and app-wide settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Server identity
    SERVER_NAME: str = os.getenv("SERVER_NAME", "Orion")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


config = Config()
