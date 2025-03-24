"""
Configuration management for Minecraft Server Manager
"""

import os
import configparser
import logging

# Configuration file location
CONFIG_FILE = "server_config.ini"

# Default configuration values
DEFAULT_CONFIG = {
    'Server': {
        'port': '25565',
        'start_command': 'start.bat',
        'inactivity_timeout': '600',
        'check_interval': '60',
        'startup_wait': '5',
        'shutdown_timeout': '30',
    },
    'RCON': {
        'enabled': 'true',
        'host': 'localhost',
        'port': '25575',
        'password': 'changeme',
        'timeout': '3',
    },
    'GUI': {
        'auto_scroll_logs': 'true',
        'theme': 'default',
        'update_interval': '1000',
        'max_log_lines': '1000',
    },
    'System': {
        'debug_mode': 'false',
    }
}

def create_default_config(config_file=CONFIG_FILE):
    """Create a default configuration file"""
    config = configparser.ConfigParser()

    # Add default sections and values
    for section, options in DEFAULT_CONFIG.items():
        config[section] = {}
        for option, value in options.items():
            config[section][option] = value

    # Write the config file
    with open(config_file, 'w') as f:
        config.write(f)

    logging.info(f"Created default configuration file: {config_file}")
    return config

def load_config(config_file=CONFIG_FILE):
    """Load configuration from file or create default if not exists"""
    config = configparser.ConfigParser()

    # Create default config if file doesn't exist
    if not os.path.exists(config_file):
        return create_default_config(config_file)

    try:
        config.read(config_file)
        logging.info(f"Loaded configuration from {config_file}")

        # Check for missing sections or options and add defaults
        for section, options in DEFAULT_CONFIG.items():
            if section not in config:
                config[section] = {}

            for option, value in options.items():
                if option not in config[section]:
                    config[section][option] = value

        return config
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
        return create_default_config(config_file)

def save_config(config, config_file=CONFIG_FILE):
    """Save configuration to file"""
    try:
        with open(config_file, 'w') as f:
            config.write(f)
        logging.info(f"Configuration saved to {config_file}")
        return True
    except Exception as e:
        logging.error(f"Failed to save configuration: {e}")
        return False