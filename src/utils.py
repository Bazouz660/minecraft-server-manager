"""
Utility functions for Minecraft Server Manager
"""

import os
import sys
import logging
import threading
import traceback
from enum import Enum, auto

# Version information
VERSION = "2.0.0"

# Server states
class ServerState(Enum):
    """Server state constants"""
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"

# Task types
class TaskType:
    """Task types for the worker queue"""
    START_SERVER = "start_server"
    STOP_SERVER = "stop_server"
    RESTART_SERVER = "restart_server"
    CHECK_STATUS = "check_status"
    GET_PLAYERS = "get_players"
    GET_STATUS = "get_status"
    GET_PERFORMANCE = "get_performance"
    RUN_COMMAND = "run_command"
    BACKUP_WORLD = "backup_world"
    LOAD_PROPERTIES = "load_properties"
    SAVE_PROPERTIES = "save_properties"
    UPDATE_JAVA_SETTINGS = "update_java_settings"
    GET_PLAYER_INFO = "get_player_info"

class Task:
    """Task object for the worker queue"""
    def __init__(self, task_type, callback=None, **kwargs):
        self.type = task_type
        self.callback = callback
        self.args = kwargs
        self.result = None
        self.error = None
        self.completed = False
        # New callback for status updates
        self.on_status_update = None

        # Performance monitor
        self.performance_monitor = PerformanceMonitor(self)

        # Server properties manager
        self.properties_manager = ServerPropertiesManager()

def setup_logging(log_file="server_manager.log", console=True, debug=False):
    """Configure logging"""
    level = logging.DEBUG if debug else logging.INFO

    # Root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # Console handler (optional)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(file_format)
        logger.addHandler(console_handler)

    logging.info(f"Logging initialized (level: {level})")
    return logger

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def check_bat_file(start_command):
    """Check if the start.bat file exists and has a pause command"""
    if not start_command.endswith('.bat'):
        return False

    if not os.path.exists(start_command):
        logging.warning(f"Start command '{start_command}' not found")
        return False

    # Read the current content
    try:
        with open(start_command, 'r') as f:
            content = f.read()

        # Add pause if needed
        if "pause" not in content.lower():
            logging.info(f"Adding 'pause' command to {start_command}")
            with open(start_command, 'a') as f:
                f.write("\n\necho. \necho Server stopped. Press any key to close window.\npause > nul")
            return True
    except Exception as e:
        logging.error(f"Error modifying batch file: {e}")

    return False

def log_exception(e, debug_mode=False):
    """Log an exception with optional stack trace for debugging"""
    logging.error(f"Error: {e}")
    if debug_mode:
        logging.error(traceback.format_exc())