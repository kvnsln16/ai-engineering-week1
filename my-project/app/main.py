import logging
from logging_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

logger.info("Application started")