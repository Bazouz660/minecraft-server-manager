"""
Main entry point for Minecraft Server Manager
"""

import os
import sys
import logging

# Internal imports
from .utils import setup_logging, check_bat_file, VERSION
from .config import load_config
from .server_manager import EnhancedServerManager  # Updated import
from .gui import ServerManagerGUI

def main():
    """Main entry point"""
    # Setup logging
    logger = setup_logging()

    try:
        # Print banner
        logging.info("=" * 70)
        logging.info(f"Minecraft Wake-on-Demand Server Manager v{VERSION}")
        logging.info("=" * 70)

        # Load configuration
        config = load_config()

        # Check and modify start.bat if needed
        check_bat_file(config.get('Server', 'start_command'))

        # Check for RCON warning
        if config.get('RCON', 'password') == 'changeme':
            logging.warning("Default RCON password detected! Please change it in the settings.")

        # Create server manager
        server_manager = EnhancedServerManager(config)  # Updated class

        # Create and run GUI
        gui = ServerManagerGUI(server_manager)
        gui.run()

    except Exception as e:
        logging.critical(f"Fatal error: {e}", exc_info=True)
        try:
            from tkinter import messagebox
            messagebox.showerror("Fatal Error", f"A critical error occurred: {e}")
        except:
            print(f"CRITICAL ERROR: {e}")

        # Force exit on exception
        if hasattr(os, '_exit'):
            os._exit(1)

if __name__ == "__main__":
    main()