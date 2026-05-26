import logging
import os

def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO")

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )