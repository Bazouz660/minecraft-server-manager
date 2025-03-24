"""
Modernized GUI implementation for Minecraft Server Manager
"""

import os
import sys
import time
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import logging
import threading
import traceback
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Internal imports
from .utils import ServerState, TaskType, log_exception, get_resource_path
from .theme_manager import ThemeManager

class TextHandler(logging.Handler):
    """Custom logging handler for Tkinter text widget"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            # Format the record
            record.message = self.format(record)

            # Put it in the queue
            self.log_queue.put(record)
        except Exception:
            self.handleError(record)

class ServerManagerGUI:
    """Modern GUI for the Minecraft server manager"""

    def __init__(self, server_manager):
        self.server_manager = server_manager

        # Load configuration
        self.config = server_manager.config
        self.auto_scroll_logs = self.config.getboolean('GUI', 'auto_scroll_logs')
        self.update_interval = self.config.getint('GUI', 'update_interval')
        self.max_log_lines = self.config.getint('GUI', 'max_log_lines')
        self.theme_name = self.config.get('GUI', 'theme', fallback='system')

        # Create the main window
        self.root = tk.Tk()
        self.root.title("Minecraft Server Manager")
        self.root.geometry("900x650")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Initialize theme manager
        self.theme_manager = ThemeManager(self.root, self.theme_name)

        # Set icon
        try:
            icon_path = get_resource_path("assets/icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            logging.debug(f"Could not load icon: {e}")

        # Variables
        self.status_var = tk.StringVar(value="Offline")
        self.player_count_var = tk.StringVar(value="0")
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.server_version_var = tk.StringVar(value="Unknown")
        self.motd_var = tk.StringVar(value="No MOTD available")
        self.max_players_var = tk.StringVar(value="0")
        self.ram_usage_var = tk.StringVar(value="0 MB")
        self.cpu_usage_var = tk.StringVar(value="0%")
        self.tps_var = tk.StringVar(value="0")

        self.log_queue = queue.Queue()

        # Performance history data
        self.ram_history = []
        self.cpu_history = []
        self.tps_history = []
        self.time_labels = []

        # Player list
        self.player_list = []

        # Set server manager callbacks
        self.server_manager.on_state_change = self.on_state_change
        self.server_manager.on_player_count_change = self.on_player_count_change
        self.server_manager.on_status_update = self.on_status_update

        # Create custom log handler
        self.log_handler = TextHandler(self.log_queue)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(self.log_handler)

        # Create GUI elements
        self.create_widgets()

        # Update timer IDs
        self.status_update_id = None
        self.log_update_id = None
        self.performance_update_id = None

        # Start update timers
        self.update_status()
        self.update_logs()
        self.update_performance()

        # Start the listener if server is not already running
        if not self.server_manager.is_server_running():
            self.server_manager.start_port_listener()

    def create_widgets(self):
        """Create all GUI elements"""
        # Main frame with padding
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create top frame for server controls and status
        self.create_top_frame()

        # Create main content area with notebook
        self.create_notebook()

        # Create status bar at bottom
        self.create_status_bar()

    def create_top_frame(self):
        """Create the top frame with controls and status summary"""
        top_frame = ttk.Frame(self.main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        # Server status card
        status_frame = ttk.LabelFrame(top_frame, text="Server Status")
        status_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        # Status indicators
        status_grid = ttk.Frame(status_frame)
        status_grid.pack(fill=tk.X, padx=10, pady=10)

        # Status indicator with colored label
        ttk.Label(status_grid, text="Status:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.status_label = ttk.Label(status_grid, textvariable=self.status_var, width=10)
        self.status_label.grid(row=0, column=1, padx=5, pady=2, sticky="w")

        ttk.Label(status_grid, text="Players:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Label(status_grid, textvariable=self.player_count_var, width=5).grid(row=0, column=3, padx=5, pady=2, sticky="w")

        ttk.Label(status_grid, text="Uptime:").grid(row=0, column=4, padx=5, pady=2, sticky="w")
        ttk.Label(status_grid, textvariable=self.uptime_var, width=12).grid(row=0, column=5, padx=5, pady=2, sticky="w")

        ttk.Label(status_grid, text="Version:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        ttk.Label(status_grid, textvariable=self.server_version_var).grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky="w")

        ttk.Label(status_grid, text="Memory:").grid(row=1, column=3, padx=5, pady=2, sticky="w")
        ttk.Label(status_grid, textvariable=self.ram_usage_var).grid(row=1, column=4, columnspan=2, padx=5, pady=2, sticky="w")

        # Control buttons frame
        controls_frame = ttk.LabelFrame(top_frame, text="Controls")
        controls_frame.pack(side=tk.RIGHT, padx=(5, 0))

        button_frame = ttk.Frame(controls_frame)
        button_frame.pack(padx=10, pady=10)

        # Main control buttons
        self.start_button = ttk.Button(button_frame, text="Start Server", command=self.on_start, width=12)
        self.start_button.grid(row=0, column=0, padx=5, pady=2)

        self.stop_button = ttk.Button(button_frame, text="Stop Server", command=self.on_stop, width=12)
        self.stop_button.grid(row=0, column=1, padx=5, pady=2)

        self.restart_button = ttk.Button(button_frame, text="Restart Server", command=self.on_restart, width=12)
        self.restart_button.grid(row=1, column=0, padx=5, pady=2)

        self.settings_button = ttk.Button(button_frame, text="Settings", command=self.on_settings, width=12)
        self.settings_button.grid(row=1, column=1, padx=5, pady=2)

    def create_notebook(self):
        """Create the main notebook with tabs"""
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Dashboard tab
        self.create_dashboard_tab()

        # Players tab
        self.create_players_tab()

        # Logs tab
        self.create_logs_tab()

        # Server Properties tab
        self.create_properties_tab()

        # Performance tab
        self.create_performance_tab()

        # About tab
        self.create_about_tab()

    def create_dashboard_tab(self):
        """Create the dashboard tab with overview information"""
        dashboard_frame = ttk.Frame(self.notebook)
        self.notebook.add(dashboard_frame, text="Dashboard")

        # Server info frame
        info_frame = ttk.LabelFrame(dashboard_frame, text="Server Information")
        info_frame.pack(fill=tk.X, padx=10, pady=10, ipady=5)

        # MOTD and basic server info
        ttk.Label(info_frame, text="MOTD:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.motd_var).grid(row=0, column=1, padx=10, pady=5, sticky="w")

        ttk.Label(info_frame, text="Max Players:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.max_players_var).grid(row=1, column=1, padx=10, pady=5, sticky="w")

        ttk.Label(info_frame, text="TPS:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.tps_var).grid(row=2, column=1, padx=10, pady=5, sticky="w")

        ttk.Label(info_frame, text="CPU Usage:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(info_frame, textvariable=self.cpu_usage_var).grid(row=3, column=1, padx=10, pady=5, sticky="w")

        # Quick actions frame
        actions_frame = ttk.LabelFrame(dashboard_frame, text="Quick Actions")
        actions_frame.pack(fill=tk.X, padx=10, pady=10, ipady=5)

        action_btns_frame = ttk.Frame(actions_frame)
        action_btns_frame.pack(padx=10, pady=10)

        # Quick action buttons
        ttk.Button(action_btns_frame, text="Backup World", command=self.on_backup_world).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(action_btns_frame, text="View Server Log", command=self.on_view_server_log).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(action_btns_frame, text="Edit server.properties", command=self.on_edit_properties).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(action_btns_frame, text="Run Console Command", command=self.on_run_command).grid(row=0, column=3, padx=5, pady=5)

        # Recent events/logs preview
        logs_preview_frame = ttk.LabelFrame(dashboard_frame, text="Recent Activity")
        logs_preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.logs_preview = scrolledtext.ScrolledText(logs_preview_frame, wrap=tk.WORD, height=10)
        self.logs_preview.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.logs_preview.config(state=tk.DISABLED)

        # Set up text tags for log levels
        self.logs_preview.tag_config("DEBUG", foreground="gray")
        self.logs_preview.tag_config("INFO", foreground="black")
        self.logs_preview.tag_config("WARNING", foreground="orange")
        self.logs_preview.tag_config("ERROR", foreground="red")
        self.logs_preview.tag_config("CRITICAL", foreground="red", font=("TkDefaultFont", 10, "bold"))

    def create_players_tab(self):
        """Create the players tab with online player management"""
        players_frame = ttk.Frame(self.notebook)
        self.notebook.add(players_frame, text="Players")

        # Online players frame
        online_frame = ttk.LabelFrame(players_frame, text="Online Players")
        online_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Player list with treeview
        players_tree_frame = ttk.Frame(online_frame)
        players_tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar for player list
        players_scroll = ttk.Scrollbar(players_tree_frame)
        players_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Player list treeview
        self.players_tree = ttk.Treeview(players_tree_frame, columns=("name", "uuid", "ip", "time"),
                              yscrollcommand=players_scroll.set, selectmode="browse")
        self.players_tree.pack(fill=tk.BOTH, expand=True)

        # Configure scrollbar
        players_scroll.config(command=self.players_tree.yview)

        # Configure columns
        self.players_tree.column("#0", width=50, stretch=tk.NO)  # Icon column
        self.players_tree.column("name", width=150, anchor=tk.W)
        self.players_tree.column("uuid", width=220, anchor=tk.W)
        self.players_tree.column("ip", width=120, anchor=tk.W)
        self.players_tree.column("time", width=100, anchor=tk.W)

        # Configure headings
        self.players_tree.heading("#0", text="")
        self.players_tree.heading("name", text="Name")
        self.players_tree.heading("uuid", text="UUID")
        self.players_tree.heading("ip", text="IP Address")
        self.players_tree.heading("time", text="Online Time")

        # Player actions frame
        player_actions = ttk.Frame(online_frame)
        player_actions.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        # Player action buttons
        ttk.Button(player_actions, text="Refresh", command=self.on_refresh_players, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="Message", command=self.on_message_player, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="Teleport", command=self.on_teleport_player, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="Kick", command=self.on_kick_player, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="Ban", command=self.on_ban_player, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="Op/Deop", command=self.on_op_player, width=15).pack(padx=5, pady=5)
        ttk.Button(player_actions, text="View Details", command=self.on_view_player, width=15).pack(padx=5, pady=5)

    def create_logs_tab(self):
        """Create the logs tab with log viewer"""
        logs_frame = ttk.Frame(self.notebook)
        self.notebook.add(logs_frame, text="Logs")

        # Log controls frame
        log_controls = ttk.Frame(logs_frame)
        log_controls.pack(fill=tk.X, padx=5, pady=5)

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=self.auto_scroll_logs)
        self.auto_scroll_check = ttk.Checkbutton(
            log_controls,
            text="Auto-scroll",
            variable=self.auto_scroll_var
        )
        self.auto_scroll_check.pack(side=tk.LEFT, padx=5)

        # Log filter
        ttk.Label(log_controls, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.log_filter_var = tk.StringVar()
        self.log_filter_entry = ttk.Entry(log_controls, textvariable=self.log_filter_var, width=30)
        self.log_filter_entry.pack(side=tk.LEFT, padx=5)

        # Log level filter
        ttk.Label(log_controls, text="Level:").pack(side=tk.LEFT, padx=5)
        self.log_level_var = tk.StringVar(value="INFO")
        log_level_combo = ttk.Combobox(log_controls, textvariable=self.log_level_var,
                                      values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                                      width=10, state="readonly")
        log_level_combo.pack(side=tk.LEFT, padx=5)

        # Clear logs button
        ttk.Button(log_controls, text="Clear", command=self.on_clear_logs).pack(side=tk.RIGHT, padx=5)

        # Export logs button
        ttk.Button(log_controls, text="Export", command=self.on_export_logs).pack(side=tk.RIGHT, padx=5)

        # Log text area
        self.log_text = scrolledtext.ScrolledText(logs_frame, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Set up text tags for log levels
        self.log_text.tag_config("DEBUG", foreground="gray")
        self.log_text.tag_config("INFO", foreground="black")
        self.log_text.tag_config("WARNING", foreground="orange")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("CRITICAL", foreground="red", font=("TkDefaultFont", 10, "bold"))

    def create_properties_tab(self):
        """Create the server properties tab for configuration"""
        properties_frame = ttk.Frame(self.notebook)
        self.notebook.add(properties_frame, text="Configuration")

        # Create a notebook for configuration sections
        config_notebook = ttk.Notebook(properties_frame)
        config_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Server Properties tab
        self.create_server_properties_tab(config_notebook)

        # Java Settings tab
        self.create_java_settings_tab(config_notebook)

        # Backup Settings tab
        self.create_backup_settings_tab(config_notebook)

        # Application Settings tab
        self.create_application_settings_tab(config_notebook)

    def create_server_properties_tab(self, parent_notebook):
        """Create the server.properties editor tab"""
        server_props_frame = ttk.Frame(parent_notebook)
        parent_notebook.add(server_props_frame, text="Server Properties")

        # Controls frame
        controls_frame = ttk.Frame(server_props_frame)
        controls_frame.pack(fill=tk.X, padx=5, pady=5)

        # Reload and save buttons
        ttk.Button(controls_frame, text="Reload", command=self.on_reload_properties).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls_frame, text="Save Changes", command=self.on_save_properties).pack(side=tk.LEFT, padx=5)

        # Property search
        ttk.Label(controls_frame, text="Search:").pack(side=tk.LEFT, padx=(20, 5))
        self.prop_search_var = tk.StringVar()
        ttk.Entry(controls_frame, textvariable=self.prop_search_var, width=25).pack(side=tk.LEFT, padx=5)

        # Properties frame
        properties_container = ttk.Frame(server_props_frame)
        properties_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Properties canvas for scrolling
        canvas = tk.Canvas(properties_container)
        scrollbar = ttk.Scrollbar(properties_container, orient="vertical", command=canvas.yview)

        self.properties_frame = ttk.Frame(canvas)
        self.properties_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=self.properties_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Dictionary to store property entry widgets
        self.property_entries = {}

        # We'll load properties in a separate method

    def create_java_settings_tab(self, parent_notebook):
        """Create the Java runtime settings tab"""
        java_frame = ttk.Frame(parent_notebook)
        parent_notebook.add(java_frame, text="Java Settings")

        # Java settings frame
        settings_frame = ttk.LabelFrame(java_frame, text="Java Runtime Settings")
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Memory settings
        memory_frame = ttk.Frame(settings_frame)
        memory_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(memory_frame, text="Minimum Memory (MB):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.min_memory_var = tk.StringVar(value="1024")
        ttk.Entry(memory_frame, textvariable=self.min_memory_var, width=8).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(memory_frame, text="Maximum Memory (MB):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.max_memory_var = tk.StringVar(value="4096")
        ttk.Entry(memory_frame, textvariable=self.max_memory_var, width=8).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # Java path
        java_path_frame = ttk.Frame(settings_frame)
        java_path_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(java_path_frame, text="Java Executable:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.java_path_var = tk.StringVar(value="java")
        java_path_entry = ttk.Entry(java_path_frame, textvariable=self.java_path_var, width=40)
        java_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(java_path_frame, text="Browse...", command=self.on_browse_java).grid(row=0, column=2, padx=5, pady=5)

        # JVM arguments
        jvm_frame = ttk.LabelFrame(settings_frame, text="JVM Arguments")
        jvm_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Preset JVM arguments
        presets_frame = ttk.Frame(jvm_frame)
        presets_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(presets_frame, text="Presets:").pack(side=tk.LEFT, padx=5)
        ttk.Button(presets_frame, text="Balanced", command=lambda: self.load_jvm_preset("balanced")).pack(side=tk.LEFT, padx=5)
        ttk.Button(presets_frame, text="Performance", command=lambda: self.load_jvm_preset("performance")).pack(side=tk.LEFT, padx=5)
        ttk.Button(presets_frame, text="Low Memory", command=lambda: self.load_jvm_preset("low_memory")).pack(side=tk.LEFT, padx=5)

        # Custom JVM arguments text area
        self.jvm_args_text = scrolledtext.ScrolledText(jvm_frame, wrap=tk.WORD, height=8)
        self.jvm_args_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.jvm_args_text.insert(tk.END, "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1")

        # Save button
        save_button = ttk.Button(settings_frame, text="Save Java Settings", command=self.on_save_java_settings)
        save_button.pack(padx=10, pady=10)

    def create_backup_settings_tab(self, parent_notebook):
        """Create the backup settings tab"""
        backup_frame = ttk.Frame(parent_notebook)
        parent_notebook.add(backup_frame, text="Backup Settings")

        # Backup settings frame
        settings_frame = ttk.LabelFrame(backup_frame, text="Automated Backup Settings")
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Enable automated backups
        self.auto_backup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings_frame, text="Enable Automated Backups",
                      variable=self.auto_backup_var).pack(anchor=tk.W, padx=10, pady=5)

        # Backup interval
        interval_frame = ttk.Frame(settings_frame)
        interval_frame.pack(fill=tk.X, padx=10, pady=5, anchor=tk.W)

        ttk.Label(interval_frame, text="Backup Interval:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.backup_interval_var = tk.StringVar(value="24")
        ttk.Entry(interval_frame, textvariable=self.backup_interval_var, width=5).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(interval_frame, text="hours").grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # Backup directory
        dir_frame = ttk.Frame(settings_frame)
        dir_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(dir_frame, text="Backup Directory:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.backup_dir_var = tk.StringVar(value="./backups")
        ttk.Entry(dir_frame, textvariable=self.backup_dir_var, width=40).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(dir_frame, text="Browse...", command=self.on_browse_backup_dir).grid(row=0, column=2, padx=5, pady=5)

        # Retention settings
        retention_frame = ttk.LabelFrame(settings_frame, text="Backup Retention")
        retention_frame.pack(fill=tk.X, padx=10, pady=10)

        # Keep last N backups
        self.keep_backups_var = tk.BooleanVar(value=True)
        keep_frame = ttk.Frame(retention_frame)
        keep_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Checkbutton(keep_frame, text="Keep last", variable=self.keep_backups_var).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.num_backups_var = tk.StringVar(value="5")
        ttk.Entry(keep_frame, textvariable=self.num_backups_var, width=5).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(keep_frame, text="backups").grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # Size limit
        self.size_limit_var = tk.BooleanVar(value=False)
        size_frame = ttk.Frame(retention_frame)
        size_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Checkbutton(size_frame, text="Limit total size to", variable=self.size_limit_var).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.max_size_var = tk.StringVar(value="5")
        ttk.Entry(size_frame, textvariable=self.max_size_var, width=5).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(size_frame, text="GB").grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # Compression settings
        compression_frame = ttk.LabelFrame(settings_frame, text="Compression")
        compression_frame.pack(fill=tk.X, padx=10, pady=10)

        self.compression_var = tk.StringVar(value="zip")
        ttk.Radiobutton(compression_frame, text="ZIP (faster, larger files)",
                       variable=self.compression_var, value="zip").pack(anchor=tk.W, padx=10, pady=5)
        ttk.Radiobutton(compression_frame, text="GZip (slower, smaller files)",
                       variable=self.compression_var, value="gzip").pack(anchor=tk.W, padx=10, pady=5)

        # Save button
        save_button = ttk.Button(settings_frame, text="Save Backup Settings", command=self.on_save_backup_settings)
        save_button.pack(padx=10, pady=10)

    def create_application_settings_tab(self, parent_notebook):
        """Create the application settings tab"""
        app_frame = ttk.Frame(parent_notebook)
        parent_notebook.add(app_frame, text="Application Settings")

        # Application settings frame
        settings_frame = ttk.LabelFrame(app_frame, text="Manager Settings")
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Connection settings
        connection_frame = ttk.Frame(settings_frame)
        connection_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(connection_frame, text="Server Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.server_port_var = tk.StringVar(value=str(self.server_manager.server_port))
        ttk.Entry(connection_frame, textvariable=self.server_port_var, width=8).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        # RCON settings
        rcon_frame = ttk.LabelFrame(settings_frame, text="RCON Settings")
        rcon_frame.pack(fill=tk.X, padx=10, pady=10)

        self.rcon_enabled_var = tk.BooleanVar(value=self.server_manager.rcon_enabled)
        ttk.Checkbutton(rcon_frame, text="Enable RCON", variable=self.rcon_enabled_var).grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Host:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.rcon_host_var = tk.StringVar(value=self.server_manager.rcon_host)
        ttk.Entry(rcon_frame, textvariable=self.rcon_host_var, width=25).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Port:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.rcon_port_var = tk.StringVar(value=str(self.server_manager.rcon_port))
        ttk.Entry(rcon_frame, textvariable=self.rcon_port_var, width=8).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Password:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.rcon_password_var = tk.StringVar(value=self.server_manager.rcon_password)
        ttk.Entry(rcon_frame, textvariable=self.rcon_password_var, width=25, show="*").grid(row=3, column=1, padx=5, pady=5, sticky="w")

        # Timeout settings
        timeout_frame = ttk.LabelFrame(settings_frame, text="Timeout Settings")
        timeout_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(timeout_frame, text="Inactivity Timeout (seconds):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.inactivity_var = tk.StringVar(value=str(self.server_manager.inactivity_timeout))
        ttk.Entry(timeout_frame, textvariable=self.inactivity_var, width=8).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(timeout_frame, text="Check Interval (seconds):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.check_interval_var = tk.StringVar(value=str(self.server_manager.check_interval))
        ttk.Entry(timeout_frame, textvariable=self.check_interval_var, width=8).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # GUI settings
        gui_frame = ttk.LabelFrame(settings_frame, text="Interface Settings")
        gui_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(gui_frame, text="UI Theme:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.theme_var = tk.StringVar(value=self.theme_name)
        theme_combo = ttk.Combobox(gui_frame, textvariable=self.theme_var,
                                 values=["system", "light", "dark", "blue", "green", "purple", "orange", "dark-blue", "cyber", "mojang", "minecraft"],
                                 state="readonly")
        theme_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(gui_frame, text="Update Interval (ms):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.update_interval_var = tk.StringVar(value=str(self.update_interval))
        ttk.Entry(gui_frame, textvariable=self.update_interval_var, width=8).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(gui_frame, text="Max Log Lines:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.max_log_lines_var = tk.StringVar(value=str(self.max_log_lines))
        ttk.Entry(gui_frame, textvariable=self.max_log_lines_var, width=8).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # Debug mode
        debug_frame = ttk.Frame(settings_frame)
        debug_frame.pack(fill=tk.X, padx=10, pady=10)

        self.debug_mode_var = tk.BooleanVar(value=self.server_manager.debug_mode)
        ttk.Checkbutton(debug_frame, text="Debug Mode", variable=self.debug_mode_var).pack(anchor=tk.W)

        # Save button
        save_button = ttk.Button(settings_frame, text="Save Application Settings", command=self.on_save_app_settings)
        save_button.pack(padx=10, pady=10)

    def create_performance_tab(self):
        """Create the performance monitoring tab"""
        performance_frame = ttk.Frame(self.notebook)
        self.notebook.add(performance_frame, text="Performance")

        # Top frame for current statistics
        stats_frame = ttk.LabelFrame(performance_frame, text="Current Server Stats")
        stats_frame.pack(fill=tk.X, padx=10, pady=10)

        # Stats grid
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(padx=10, pady=10)

        # Memory usage
        ttk.Label(stats_grid, text="Memory Usage:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.memory_bar = ttk.Progressbar(stats_grid, length=200, mode="determinate")
        self.memory_bar.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        ttk.Label(stats_grid, textvariable=self.ram_usage_var).grid(row=0, column=2, padx=10, pady=5, sticky="w")

        # CPU usage
        ttk.Label(stats_grid, text="CPU Usage:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.cpu_bar = ttk.Progressbar(stats_grid, length=200, mode="determinate")
        self.cpu_bar.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        ttk.Label(stats_grid, textvariable=self.cpu_usage_var).grid(row=1, column=2, padx=10, pady=5, sticky="w")

        # TPS
        ttk.Label(stats_grid, text="TPS:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.tps_bar = ttk.Progressbar(stats_grid, length=200, mode="determinate")
        self.tps_bar.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        ttk.Label(stats_grid, textvariable=self.tps_var).grid(row=2, column=2, padx=10, pady=5, sticky="w")

        # Performance graphs frame
        graphs_frame = ttk.LabelFrame(performance_frame, text="Performance History")
        graphs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Timeframe selection
        timeframe_frame = ttk.Frame(graphs_frame)
        timeframe_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(timeframe_frame, text="Timeframe:").pack(side=tk.LEFT, padx=5)
        self.timeframe_var = tk.StringVar(value="1 hour")
        timeframe_combo = ttk.Combobox(timeframe_frame, textvariable=self.timeframe_var,
                                     values=["15 minutes", "1 hour", "6 hours", "24 hours"],
                                     state="readonly", width=10)
        timeframe_combo.pack(side=tk.LEFT, padx=5)
        timeframe_combo.bind("<<ComboboxSelected>>", self.on_timeframe_change)

        ttk.Button(timeframe_frame, text="Refresh", command=self.on_refresh_graphs).pack(side=tk.LEFT, padx=5)

        # Graph tabs
        graph_notebook = ttk.Notebook(graphs_frame)
        graph_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Memory graph tab
        self.memory_frame = ttk.Frame(graph_notebook)
        graph_notebook.add(self.memory_frame, text="Memory")

        # CPU graph tab
        self.cpu_frame = ttk.Frame(graph_notebook)
        graph_notebook.add(self.cpu_frame, text="CPU")

        # TPS graph tab
        self.tps_frame = ttk.Frame(graph_notebook)
        graph_notebook.add(self.tps_frame, text="TPS")

        # Initialize empty graphs
        self.init_performance_graphs()

    def init_performance_graphs(self):
        """Initialize the performance graphs"""
        # Set up memory graph
        self.memory_figure = plt.Figure(figsize=(7, 4), dpi=100)
        self.memory_plot = self.memory_figure.add_subplot(111)
        self.memory_canvas = FigureCanvasTkAgg(self.memory_figure, self.memory_frame)
        self.memory_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Set up CPU graph
        self.cpu_figure = plt.Figure(figsize=(7, 4), dpi=100)
        self.cpu_plot = self.cpu_figure.add_subplot(111)
        self.cpu_canvas = FigureCanvasTkAgg(self.cpu_figure, self.cpu_frame)
        self.cpu_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Set up TPS graph
        self.tps_figure = plt.Figure(figsize=(7, 4), dpi=100)
        self.tps_plot = self.tps_figure.add_subplot(111)
        self.tps_canvas = FigureCanvasTkAgg(self.tps_figure, self.tps_frame)
        self.tps_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Update graphs with empty data
        self.update_performance_graphs()

    def update_performance_graphs(self):
        """Update the performance graphs with current data"""
        # Update memory graph
        self.memory_plot.clear()
        if self.ram_history:
            self.memory_plot.plot(self.time_labels, self.ram_history, 'b-')
            self.memory_plot.set_title('Memory Usage Over Time')
            self.memory_plot.set_xlabel('Time')
            self.memory_plot.set_ylabel('Memory Usage (MB)')
            self.memory_plot.grid(True)
            self.memory_figure.tight_layout()
            self.memory_canvas.draw()

        # Update CPU graph
        self.cpu_plot.clear()
        if self.cpu_history:
            self.cpu_plot.plot(self.time_labels, self.cpu_history, 'r-')
            self.cpu_plot.set_title('CPU Usage Over Time')
            self.cpu_plot.set_xlabel('Time')
            self.cpu_plot.set_ylabel('CPU Usage (%)')
            self.cpu_plot.grid(True)
            self.cpu_figure.tight_layout()
            self.cpu_canvas.draw()

        # Update TPS graph
        self.tps_plot.clear()
        if self.tps_history:
            self.tps_plot.plot(self.time_labels, self.tps_history, 'g-')
            self.tps_plot.set_title('TPS Over Time')
            self.tps_plot.set_xlabel('Time')
            self.tps_plot.set_ylabel('Ticks Per Second')
            self.tps_plot.grid(True)
            self.tps_figure.tight_layout()
            self.tps_canvas.draw()

    def create_about_tab(self):
        """Create the about tab"""
        about_frame = ttk.Frame(self.notebook)
        self.notebook.add(about_frame, text="About")

        # About text
        from .utils import VERSION
        about_text = f"""
        Minecraft Wake-on-Demand Server Manager v{VERSION}

        This application manages your Minecraft server by:
        • Starting the server when players try to connect
        • Monitoring player activity and server performance
        • Shutting down the server after a period of inactivity
        • Providing a user-friendly interface for server management

        Features:
        • Wake-on-Demand: Server starts automatically when players try to connect
        • Resource Optimization: Server shuts down when inactive to save resources
        • Performance Monitoring: Track server resource usage and performance
        • Advanced Configuration: Easily configure server and Java settings

        Created by Claude AI
        """
        about_label = ttk.Label(about_frame, text=about_text, wraplength=700, justify="center")
        about_label.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

    def create_status_bar(self):
        """Create the status bar at the bottom of the window"""
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # Event handlers
    def on_state_change(self, old_state, new_state):
        """Callback for server state changes"""
        # Update status text and color
        self.status_var.set(new_state.name)

        if new_state == ServerState.OFFLINE:
            self.status_label.config(foreground="red")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.restart_button.config(state=tk.DISABLED)
            self.status_bar.config(text="Server is offline")
        elif new_state == ServerState.STARTING:
            self.status_label.config(foreground="orange")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.restart_button.config(state=tk.DISABLED)
            self.status_bar.config(text="Server is starting...")
        elif new_state == ServerState.RUNNING:
            self.status_label.config(foreground="green")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.restart_button.config(state=tk.NORMAL)
            self.status_bar.config(text="Server is running")
        elif new_state == ServerState.STOPPING:
            self.status_label.config(foreground="orange")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.restart_button.config(state=tk.DISABLED)
            self.status_bar.config(text="Server is stopping...")

    def on_player_count_change(self, count):
        """Callback for player count changes"""
        self.player_count_var.set(str(count))

    def on_status_update(self, status_data):
        """Callback for server status updates"""
        # Update server info from status data
        if not status_data:
            return

        if 'version' in status_data:
            self.server_version_var.set(status_data['version'])

        if 'motd' in status_data:
            self.motd_var.set(status_data['motd'])

        if 'max_players' in status_data:
            self.max_players_var.set(str(status_data['max_players']))

        if 'players' in status_data and 'online' in status_data['players']:
            self.player_count_var.set(str(status_data['players']['online']))

        if 'players' in status_data and 'sample' in status_data['players']:
            self.update_player_list(status_data['players']['sample'])

        if 'performance' in status_data:
            perf = status_data['performance']

            if 'ram' in perf:
                ram_mb = perf['ram']
                self.ram_usage_var.set(f"{ram_mb} MB")

                # Update RAM history
                if len(self.ram_history) > 100:  # Keep last 100 data points
                    self.ram_history.pop(0)
                    self.time_labels.pop(0)

                self.ram_history.append(ram_mb)
                self.time_labels.append(len(self.ram_history))

                # Update memory bar
                if 'ram_max' in perf and perf['ram_max'] > 0:
                    percent = min(100, int(ram_mb / perf['ram_max'] * 100))
                    self.memory_bar['value'] = percent

            if 'cpu' in perf:
                cpu_percent = perf['cpu']
                self.cpu_usage_var.set(f"{cpu_percent}%")

                # Update CPU history
                if len(self.cpu_history) > 100:
                    self.cpu_history.pop(0)

                self.cpu_history.append(cpu_percent)

                # Update CPU bar
                self.cpu_bar['value'] = min(100, cpu_percent)

            if 'tps' in perf:
                tps = perf['tps']
                self.tps_var.set(f"{tps}")

                # Update TPS history
                if len(self.tps_history) > 100:
                    self.tps_history.pop(0)

                self.tps_history.append(tps)

                # Update TPS bar (20 is optimal)
                tps_percent = min(100, int(tps / 20 * 100))
                self.tps_bar['value'] = tps_percent

    def update_player_list(self, players):
        """Update the player list display"""
        # Clear existing entries
        for item in self.players_tree.get_children():
            self.players_tree.delete(item)

        # Add players to the list
        for player in players:
            self.players_tree.insert("", "end", values=(
                player.get('name', 'Unknown'),
                player.get('id', 'Unknown'),
                player.get('ip', 'Unknown'),
                player.get('online_time', 'Unknown')
            ))

        # Update the player list
        self.player_list = players

    def update_status(self):
        """Update the status display"""
        try:
            # Update UI based on current state
            server_state = self.server_manager.get_state()

            # Update uptime if server is running
            if server_state == ServerState.RUNNING:
                uptime_secs = int(time.time() - self.server_manager.start_time)
                hours, remainder = divmod(uptime_secs, 3600)
                minutes, seconds = divmod(remainder, 60)
                self.uptime_var.set(f"{hours:02}:{minutes:02}:{seconds:02}")

            # Periodically check server status in the background (non-blocking)
            if server_state in [ServerState.RUNNING, ServerState.STARTING]:
                self.server_manager.queue_task(TaskType.CHECK_STATUS)

        except Exception as e:
            log_exception(e, self.server_manager.debug_mode)

        # Schedule next update
        self.status_update_id = self.root.after(self.update_interval, self.update_status)

    def update_logs(self):
        """Update the log text area with new log messages"""
        # Process all queued log messages
        while not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                self.add_log_message(record)
            except queue.Empty:
                break

        # Schedule next update
        self.log_update_id = self.root.after(100, self.update_logs)

    def update_performance(self):
        """Update performance data periodically"""
        if self.server_manager.get_state() == ServerState.RUNNING:
            # Queue performance update task
            self.server_manager.queue_task(TaskType.GET_PERFORMANCE)

            # Update the graphs if we have data
            if self.ram_history and self.cpu_history and self.tps_history:
                self.update_performance_graphs()

        # Schedule next update
        self.performance_update_id = self.root.after(5000, self.update_performance)  # Update every 5 seconds

    def add_log_message(self, record):
        """Add a log message to the log text area"""
        try:
            # Get the log level tag
            tag = record.levelname

            # Add the message to the text widget
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, record.message + "\n", tag)

            # Limit the number of lines
            num_lines = int(self.log_text.index(tk.END).split('.')[0]) - 1
            if num_lines > self.max_log_lines:
                self.log_text.delete(1.0, f"{num_lines - self.max_log_lines + 1}.0")

            # Auto-scroll if enabled
            if self.auto_scroll_var.get():
                self.log_text.see(tk.END)

            self.log_text.config(state=tk.DISABLED)

            # Also add to logs preview on dashboard (last 10 lines only)
            self.logs_preview.config(state=tk.NORMAL)
            self.logs_preview.insert(tk.END, record.message + "\n", tag)

            # Keep only last 10 lines in preview
            preview_lines = int(self.logs_preview.index(tk.END).split('.')[0]) - 1
            if preview_lines > 10:
                self.logs_preview.delete(1.0, f"{preview_lines - 10 + 1}.0")

            # Always auto-scroll preview
            self.logs_preview.see(tk.END)
            self.logs_preview.config(state=tk.DISABLED)

        except Exception as e:
            print(f"Error adding log message: {e}")

    # Button handlers
    def on_start(self):
        """Start server button handler"""
        self.status_bar.config(text="Starting server...")
        self.server_manager.start_server(self.on_server_operation_result)

    def on_stop(self):
        """Stop server button handler"""
        if messagebox.askyesno("Confirm", "Are you sure you want to stop the server?"):
            self.status_bar.config(text="Stopping server...")
            self.server_manager.stop_server(self.on_server_operation_result)

    def on_restart(self):
        """Restart server button handler"""
        if messagebox.askyesno("Confirm", "Are you sure you want to restart the server?"):
            self.status_bar.config(text="Restarting server...")
            self.server_manager.restart_server(self.on_server_operation_result)

    def on_server_operation_result(self, task):
        """Callback for server operation task completion"""
        if task.error:
            messagebox.showerror("Error", f"Operation failed: {task.error}")
            self.status_bar.config(text=f"Error: {task.error}")
        else:
            self.status_bar.config(text=f"{task.type} completed")

    def on_settings(self):
        """Settings button handler - switch to configuration tab"""
        self.notebook.select(3)  # Select the Configuration tab

    def on_backup_world(self):
        """Backup world button handler"""
        if self.server_manager.get_state() == ServerState.RUNNING:
            result = messagebox.askyesnocancel("Backup World",
                               "Creating a backup while the server is running may cause lag.\n\n"
                               "• Yes: Continue with backup\n"
                               "• No: Stop server and then backup\n"
                               "• Cancel: Abort backup")

            if result is None:  # Cancel
                return
            elif result is False:  # No - stop server first
                self.server_manager.stop_server(lambda task: self.do_backup_world())
                return

        self.do_backup_world()

    def do_backup_world(self):
        """Perform the world backup"""
        self.status_bar.config(text="Creating world backup...")
        self.server_manager.queue_task(TaskType.BACKUP_WORLD, self.on_backup_complete)

    def on_backup_complete(self, task):
        """Callback for backup completion"""
        if task.error:
            messagebox.showerror("Backup Error", f"Failed to create backup: {task.error}")
            self.status_bar.config(text=f"Backup failed: {task.error}")
        else:
            messagebox.showinfo("Backup Complete", f"World backup created successfully at {task.result}")
            self.status_bar.config(text="World backup completed")

    def on_view_server_log(self):
        """View server log button handler"""
        try:
            log_path = "./logs/latest.log"
            if os.path.exists(log_path):
                if sys.platform == "win32":
                    os.system(f'start notepad "{log_path}"')
                elif sys.platform == "darwin":  # macOS
                    os.system(f'open "{log_path}"')
                else:  # Linux/Unix
                    os.system(f'xdg-open "{log_path}"')
            else:
                messagebox.showinfo("Info", "Server log file not found. The server may not have created a log file yet.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open log file: {e}")

    def on_edit_properties(self):
        """Edit server.properties button handler"""
        self.notebook.select(3)  # Select the Configuration tab

    def on_run_command(self):
        """Run console command button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to execute commands")
            return

        # Create command input dialog
        command_dialog = tk.Toplevel(self.root)
        command_dialog.title("Run Console Command")
        command_dialog.geometry("500x300")
        command_dialog.transient(self.root)
        command_dialog.grab_set()

        ttk.Label(command_dialog, text="Enter Minecraft console command:").pack(padx=10, pady=10)

        # Command entry
        command_var = tk.StringVar()
        command_entry = ttk.Entry(command_dialog, textvariable=command_var, width=50)
        command_entry.pack(padx=10, pady=5, fill=tk.X)
        command_entry.focus_set()

        # Result display
        ttk.Label(command_dialog, text="Result:").pack(padx=10, pady=5, anchor=tk.W)
        result_text = scrolledtext.ScrolledText(command_dialog, wrap=tk.WORD, height=10)
        result_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        result_text.config(state=tk.DISABLED)

        def execute_command():
            cmd = command_var.get().strip()
            if not cmd:
                return

            result_text.config(state=tk.NORMAL)
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, "Executing command...\n")
            result_text.config(state=tk.DISABLED)

            # Queue the command task
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: display_result(task),
                                      command=cmd)

        def display_result(task):
            result_text.config(state=tk.NORMAL)
            result_text.delete(1.0, tk.END)

            if task.error:
                result_text.insert(tk.END, f"Error: {task.error}\n", "error")
            else:
                result_text.insert(tk.END, f"{task.result}\n")

            result_text.config(state=tk.DISABLED)

        # Buttons frame
        buttons_frame = ttk.Frame(command_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(buttons_frame, text="Execute", command=execute_command).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Close", command=command_dialog.destroy).pack(side=tk.RIGHT, padx=5)

        # Set up text tags
        result_text.tag_config("error", foreground="red")

        # Bind Enter key to execute
        command_entry.bind("<Return>", lambda event: execute_command())

    def on_refresh_players(self):
        """Refresh player list button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to refresh player list")
            return

        self.server_manager.queue_task(TaskType.GET_PLAYERS)
        self.status_bar.config(text="Refreshing player list...")

    def on_message_player(self):
        """Message selected player button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to message players")
            return

        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to message")
            return

        player_name = self.players_tree.item(selected[0])['values'][0]

        # Create message dialog
        msg_dialog = tk.Toplevel(self.root)
        msg_dialog.title(f"Message to {player_name}")
        msg_dialog.geometry("400x200")
        msg_dialog.transient(self.root)
        msg_dialog.grab_set()

        ttk.Label(msg_dialog, text=f"Enter message for {player_name}:").pack(padx=10, pady=10, anchor=tk.W)

        msg_var = tk.StringVar()
        msg_entry = ttk.Entry(msg_dialog, textvariable=msg_var, width=50)
        msg_entry.pack(padx=10, pady=5, fill=tk.X)
        msg_entry.focus_set()

        buttons_frame = ttk.Frame(msg_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        def send_message():
            msg = msg_var.get().strip()
            if not msg:
                return

            # Send the message
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: msg_dialog.destroy() if not task.error else messagebox.showerror("Error", f"Failed to send message: {task.error}"),
                                      command=f"tell {player_name} {msg}")

        ttk.Button(buttons_frame, text="Send", command=send_message).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=msg_dialog.destroy).pack(side=tk.RIGHT, padx=5)

        msg_entry.bind("<Return>", lambda event: send_message())

    def on_teleport_player(self):
        """Teleport selected player button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to teleport players")
            return

        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to teleport")
            return

        player_name = self.players_tree.item(selected[0])['values'][0]

        # Create teleport dialog
        tp_dialog = tk.Toplevel(self.root)
        tp_dialog.title(f"Teleport {player_name}")
        tp_dialog.geometry("400x250")
        tp_dialog.transient(self.root)
        tp_dialog.grab_set()

        ttk.Label(tp_dialog, text=f"Teleport {player_name} to:").pack(padx=10, pady=10, anchor=tk.W)

        # Teleport options frame
        options_frame = ttk.Frame(tp_dialog)
        options_frame.pack(fill=tk.X, padx=10, pady=5)

        # Teleport option
        tp_option = tk.StringVar(value="coordinates")
        ttk.Radiobutton(options_frame, text="Coordinates", variable=tp_option, value="coordinates").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Radiobutton(options_frame, text="Player", variable=tp_option, value="player").grid(row=1, column=0, padx=5, pady=5, sticky="w")

        # Coordinates entry
        coords_frame = ttk.Frame(options_frame)
        coords_frame.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(coords_frame, text="X:").grid(row=0, column=0, padx=2)
        x_var = tk.StringVar(value="0")
        ttk.Entry(coords_frame, textvariable=x_var, width=8).grid(row=0, column=1, padx=2)

        ttk.Label(coords_frame, text="Y:").grid(row=0, column=2, padx=2)
        y_var = tk.StringVar(value="70")
        ttk.Entry(coords_frame, textvariable=y_var, width=8).grid(row=0, column=3, padx=2)

        ttk.Label(coords_frame, text="Z:").grid(row=0, column=4, padx=2)
        z_var = tk.StringVar(value="0")
        ttk.Entry(coords_frame, textvariable=z_var, width=8).grid(row=0, column=5, padx=2)

        # Player entry
        player_frame = ttk.Frame(options_frame)
        player_frame.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(player_frame, text="Player:").grid(row=0, column=0, padx=2)
        target_var = tk.StringVar()

        # Get other player names for dropdown
        other_players = []
        for item in self.players_tree.get_children():
            name = self.players_tree.item(item)['values'][0]
            if name != player_name:
                other_players.append(name)

        if other_players:
            player_combo = ttk.Combobox(player_frame, textvariable=target_var, values=other_players, width=20)
            player_combo.grid(row=0, column=1, padx=2)
        else:
            ttk.Entry(player_frame, textvariable=target_var, width=20).grid(row=0, column=1, padx=2)

        # Buttons frame
        buttons_frame = ttk.Frame(tp_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        def execute_teleport():
            option = tp_option.get()
            command = ""

            if option == "coordinates":
                try:
                    x = float(x_var.get())
                    y = float(y_var.get())
                    z = float(z_var.get())
                    command = f"tp {player_name} {x} {y} {z}"
                except ValueError:
                    messagebox.showerror("Error", "Coordinates must be valid numbers")
                    return
            else:  # player option
                target = target_var.get().strip()
                if not target:
                    messagebox.showerror("Error", "Please enter a target player")
                    return
                command = f"tp {player_name} {target}"

            # Execute teleport command
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: on_teleport_result(task),
                                      command=command)

        def on_teleport_result(task):
            if task.error:
                messagebox.showerror("Error", f"Teleport failed: {task.error}")
            else:
                tp_dialog.destroy()
                self.status_bar.config(text=f"Teleported {player_name}")

        ttk.Button(buttons_frame, text="Teleport", command=execute_teleport).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=tp_dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def on_kick_player(self):
        """Kick selected player button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to kick players")
            return

        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to kick")
            return

        player_name = self.players_tree.item(selected[0])['values'][0]

        # Ask for confirmation and reason
        kick_dialog = tk.Toplevel(self.root)
        kick_dialog.title(f"Kick {player_name}")
        kick_dialog.geometry("400x200")
        kick_dialog.transient(self.root)
        kick_dialog.grab_set()

        ttk.Label(kick_dialog, text=f"Kick player {player_name}").pack(padx=10, pady=10)

        ttk.Label(kick_dialog, text="Reason:").pack(padx=10, pady=5, anchor=tk.W)
        reason_var = tk.StringVar(value="You have been kicked from the server")
        ttk.Entry(kick_dialog, textvariable=reason_var, width=50).pack(padx=10, pady=5, fill=tk.X)

        buttons_frame = ttk.Frame(kick_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        def execute_kick():
            reason = reason_var.get()
            command = f'kick {player_name} {reason}'

            # Execute kick command
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: on_kick_result(task),
                                      command=command)

        def on_kick_result(task):
            if task.error:
                messagebox.showerror("Error", f"Kick failed: {task.error}")
            else:
                kick_dialog.destroy()
                self.status_bar.config(text=f"Kicked {player_name}")
                self.on_refresh_players()

        ttk.Button(buttons_frame, text="Kick Player", command=execute_kick).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=kick_dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def on_ban_player(self):
        """Ban selected player button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to ban players")
            return

        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to ban")
            return

        player_name = self.players_tree.item(selected[0])['values'][0]

        # Ask for confirmation and reason
        ban_dialog = tk.Toplevel(self.root)
        ban_dialog.title(f"Ban {player_name}")
        ban_dialog.geometry("400x250")
        ban_dialog.transient(self.root)
        ban_dialog.grab_set()

        ttk.Label(ban_dialog, text=f"Ban player {player_name}").pack(padx=10, pady=10)

        # Ban type
        ban_type_frame = ttk.Frame(ban_dialog)
        ban_type_frame.pack(fill=tk.X, padx=10, pady=5)

        ban_type = tk.StringVar(value="player")
        ttk.Radiobutton(ban_type_frame, text="Ban player", variable=ban_type, value="player").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(ban_type_frame, text="Ban IP", variable=ban_type, value="ip").pack(side=tk.LEFT, padx=5)

        ttk.Label(ban_dialog, text="Reason:").pack(padx=10, pady=5, anchor=tk.W)
        reason_var = tk.StringVar(value="Banned from the server")
        ttk.Entry(ban_dialog, textvariable=reason_var, width=50).pack(padx=10, pady=5, fill=tk.X)

        buttons_frame = ttk.Frame(ban_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        def execute_ban():
            reason = reason_var.get()
            if ban_type.get() == "player":
                command = f'ban {player_name} {reason}'
            else:
                command = f'ban-ip {player_name} {reason}'

            # Execute ban command
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: on_ban_result(task),
                                      command=command)

        def on_ban_result(task):
            if task.error:
                messagebox.showerror("Error", f"Ban failed: {task.error}")
            else:
                ban_dialog.destroy()
                self.status_bar.config(text=f"Banned {player_name}")
                self.on_refresh_players()

        ttk.Button(buttons_frame, text="Ban Player", command=execute_ban).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=ban_dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def on_op_player(self):
        """Op/Deop selected player button handler"""
        if self.server_manager.get_state() != ServerState.RUNNING:
            messagebox.showinfo("Info", "Server must be running to change operator status")
            return

        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player")
            return

        player_name = self.players_tree.item(selected[0])['values'][0]

        # Ask for op or deop
        op_dialog = tk.Toplevel(self.root)
        op_dialog.title(f"Operator Status: {player_name}")
        op_dialog.geometry("300x150")
        op_dialog.transient(self.root)
        op_dialog.grab_set()

        ttk.Label(op_dialog, text=f"Change operator status for {player_name}").pack(padx=10, pady=10)

        buttons_frame = ttk.Frame(op_dialog)
        buttons_frame.pack(fill=tk.X, padx=10, pady=20)

        def execute_op(is_op):
            command = f'{"op" if is_op else "deop"} {player_name}'

            # Execute command
            self.server_manager.queue_task(TaskType.RUN_COMMAND,
                                      lambda task: on_op_result(task, is_op),
                                      command=command)

        def on_op_result(task, is_op):
            if task.error:
                messagebox.showerror("Error", f"Command failed: {task.error}")
            else:
                op_dialog.destroy()
                status = "operator" if is_op else "regular player"
                self.status_bar.config(text=f"Changed {player_name} to {status}")

        ttk.Button(buttons_frame, text="Make Operator",
                 command=lambda: execute_op(True)).pack(side=tk.LEFT, padx=10)
        ttk.Button(buttons_frame, text="Remove Operator",
                 command=lambda: execute_op(False)).pack(side=tk.RIGHT, padx=10)
        ttk.Button(op_dialog, text="Cancel",
                 command=op_dialog.destroy).pack(side=tk.BOTTOM, pady=10)

    def on_view_player(self):
        """View details for the selected player"""
        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to view")
            return

        values = self.players_tree.item(selected[0])['values']
        if len(values) < 4:
            messagebox.showinfo("Info", "Player information not available")
            return

        player_name = values[0]
        player_uuid = values[1]
        player_ip = values[2]
        player_time = values[3]

        # Create details dialog
        details_dialog = tk.Toplevel(self.root)
        details_dialog.title(f"Player Details: {player_name}")
        details_dialog.geometry("400x300")
        details_dialog.transient(self.root)
        details_dialog.grab_set()

        ttk.Label(details_dialog, text=player_name, font=("TkDefaultFont", 14, "bold")).pack(padx=10, pady=10)

        details_frame = ttk.Frame(details_dialog)
        details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(details_frame, text="UUID:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_uuid).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(details_frame, text="IP Address:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_ip).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(details_frame, text="Online Time:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_time).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # If server is running, fetch more details
        if self.server_manager.get_state() == ServerState.RUNNING:
            # Fetch player stats like health, position, etc.
            self.server_manager.queue_task(TaskType.GET_PLAYER_INFO,
                                      lambda task: update_player_info(task),
                                      player_name=player_name)

        def update_player_info(task):
            if task.error:
                ttk.Label(details_frame, text="Failed to fetch additional details",
                        foreground="red").grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="w")
                return

            info = task.result
            row = 3
            for key, value in info.items():
                ttk.Label(details_frame, text=f"{key}:").grid(row=row, column=0, padx=5, pady=5, sticky="w")
                ttk.Label(details_frame, text=str(value)).grid(row=row, column=1, padx=5, pady=5, sticky="w")
                row += 1

        ttk.Button(details_dialog, text="Close", command=details_dialog.destroy).pack(pady=10)

    def on_reload_properties(self):
        """Reload server properties from file"""
        self.server_manager.queue_task(TaskType.LOAD_PROPERTIES,
                                  lambda task: self.load_properties_to_ui(task.result))
        self.status_bar.config(text="Reloading server properties...")

    def load_properties_to_ui(self, properties):
        """Load server properties into the UI"""
        # Clear existing property entries
        for widget in self.properties_frame.winfo_children():
            widget.destroy()

        # Reset property entries dictionary
        self.property_entries = {}

        # Add each property to the UI
        row = 0
        for key, value in sorted(properties.items()):
            # Create a frame for this property
            prop_frame = ttk.Frame(self.properties_frame)
            prop_frame.grid(row=row, column=0, padx=5, pady=2, sticky="ew")

            # Property label
            ttk.Label(prop_frame, text=key, width=25, anchor="w").grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Property entry depends on type
            if isinstance(value, bool) or value.lower() in ['true', 'false']:
                # Boolean property
                var = tk.BooleanVar(value=str(value).lower() == 'true')
                widget = ttk.Checkbutton(prop_frame, variable=var)
                widget.grid(row=0, column=1, padx=5, pady=2, sticky="w")
                self.property_entries[key] = (var, 'bool')
            else:
                # Text property
                var = tk.StringVar(value=value)
                widget = ttk.Entry(prop_frame, textvariable=var, width=40)
                widget.grid(row=0, column=1, padx=5, pady=2, sticky="w")
                self.property_entries[key] = (var, 'text')

            row += 1

        self.status_bar.config(text="Server properties loaded")

    def on_save_properties(self):
        """Save modified server properties"""
        # Collect modified properties
        properties = {}
        for key, (var, prop_type) in self.property_entries.items():
            if prop_type == 'bool':
                properties[key] = str(var.get()).lower()
            else:
                properties[key] = var.get()

        # Queue save task
        self.server_manager.queue_task(TaskType.SAVE_PROPERTIES,
                                  lambda task: self.on_properties_saved(task),
                                  properties=properties)
        self.status_bar.config(text="Saving server properties...")

    def on_properties_saved(self, task):
        """Handle properties save completion"""
        if task.error:
            messagebox.showerror("Error", f"Failed to save properties: {task.error}")
            self.status_bar.config(text="Failed to save properties")
        else:
            messagebox.showinfo("Success", "Server properties saved successfully.\n\nServer restart may be required for some settings to take effect.")
            self.status_bar.config(text="Server properties saved")

    def load_jvm_preset(self, preset):
        """Load a JVM arguments preset"""
        if preset == "balanced":
            args = "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1"
        elif preset == "performance":
            args = "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=100 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=40 -XX:G1MaxNewSizePercent=50 -XX:G1HeapRegionSize=16M -XX:G1ReservePercent=15 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=20 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true"
        elif preset == "low_memory":
            args = "-XX:+UseG1GC -XX:MaxGCPauseMillis=100 -XX:+DisableExplicitGC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:G1HeapRegionSize=4M -XX:G1MixedGCCountTarget=8 -XX:InitiatingHeapOccupancyPercent=25 -XX:G1MixedGCLiveThresholdPercent=90 -XX:SurvivorRatio=32 -XX:MaxTenuringThreshold=1"

        self.jvm_args_text.delete(1.0, tk.END)
        self.jvm_args_text.insert(tk.END, args)

    def on_save_java_settings(self):
        """Save Java settings"""
        try:
            min_memory = int(self.min_memory_var.get())
            max_memory = int(self.max_memory_var.get())
            java_path = self.java_path_var.get()
            jvm_args = self.jvm_args_text.get(1.0, tk.END).strip()

            # Validate memory settings
            if min_memory < 512:
                messagebox.showwarning("Warning", "Minimum memory should be at least 512MB")
                min_memory = 512
                self.min_memory_var.set("512")

            if max_memory < min_memory:
                messagebox.showwarning("Warning", "Maximum memory cannot be less than minimum memory")
                max_memory = min_memory
                self.max_memory_var.set(str(min_memory))

            if max_memory > 16384:  # 16GB
                result = messagebox.askyesno("Warning",
                             f"Setting maximum memory to {max_memory}MB is quite high. Are you sure?")
                if not result:
                    return

            # Save the settings
            self.server_manager.update_java_settings(min_memory, max_memory, jvm_args, self.on_java_settings_saved)
            self.status_bar.config(text="Saving Java settings...")

        except ValueError:
            messagebox.showerror("Error", "Memory values must be valid numbers")

    def on_java_settings_saved(self, task):
        """Handle Java settings save result"""
        if task.error:
            messagebox.showerror("Error", f"Failed to save Java settings: {task.error}")
            self.status_bar.config(text="Failed to save Java settings")
        else:
            messagebox.showinfo("Success", "Java settings saved successfully.\n\nThe changes will take effect when the server is next started.")
            self.status_bar.config(text="Java settings saved successfully")

    def on_save_backup_settings(self):
        """Save backup settings"""
        try:
            backup_enabled = self.auto_backup_var.get()
            backup_interval = int(self.backup_interval_var.get())
            backup_dir = self.backup_dir_var.get()

            # Validate settings
            if backup_interval < 1:
                messagebox.showwarning("Warning", "Backup interval must be at least 1 hour")
                backup_interval = 1
                self.backup_interval_var.set("1")

            if not os.path.exists(backup_dir):
                result = messagebox.askyesno("Warning",
                             f"Backup directory '{backup_dir}' does not exist. Create it?")
                if result:
                    os.makedirs(backup_dir, exist_ok=True)
                else:
                    return

            # Get retention settings
            keep_last = self.keep_backups_var.get()
            num_backups = int(self.num_backups_var.get()) if keep_last else 0
            size_limit = self.size_limit_var.get()
            max_size = int(self.max_size_var.get()) if size_limit else 0

            # Get compression type
            compression = self.compression_var.get()

            # Save settings to config
            self.server_manager.config.set('Backup', 'enabled', str(backup_enabled))
            self.server_manager.config.set('Backup', 'interval', str(backup_interval))
            self.server_manager.config.set('Backup', 'directory', backup_dir)
            self.server_manager.config.set('Backup', 'keep_last', str(keep_last))
            self.server_manager.config.set('Backup', 'num_backups', str(num_backups))
            self.server_manager.config.set('Backup', 'size_limit', str(size_limit))
            self.server_manager.config.set('Backup', 'max_size', str(max_size))
            self.server_manager.config.set('Backup', 'compression', compression)

            # Save config
            from .config import save_config
            save_config(self.server_manager.config)

            messagebox.showinfo("Success", "Backup settings saved successfully")
            self.status_bar.config(text="Backup settings saved")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save backup settings: {e}")

    def on_save_app_settings(self):
        """Save application settings"""
        try:
            # Get settings from UI
            server_port = int(self.server_port_var.get())
            rcon_enabled = self.rcon_enabled_var.get()
            rcon_host = self.rcon_host_var.get()
            rcon_port = int(self.rcon_port_var.get())
            rcon_password = self.rcon_password_var.get()
            inactivity_timeout = int(self.inactivity_var.get())
            check_interval = int(self.check_interval_var.get())
            update_interval = int(self.update_interval_var.get())
            max_log_lines = int(self.max_log_lines_var.get())
            debug_mode = self.debug_mode_var.get()
            theme = self.theme_var.get()

            # Validate settings
            if server_port < 1 or server_port > 65535:
                messagebox.showwarning("Warning", "Server port must be between 1 and 65535")
                server_port = 25565
                self.server_port_var.set("25565")

            if rcon_port < 1 or rcon_port > 65535:
                messagebox.showwarning("Warning", "RCON port must be between 1 and 65535")
                rcon_port = 25575
                self.rcon_port_var.set("25575")

            if inactivity_timeout < 60:
                messagebox.showwarning("Warning", "Inactivity timeout should be at least 60 seconds")
                inactivity_timeout = 60
                self.inactivity_var.set("60")

            if check_interval < 10:
                messagebox.showwarning("Warning", "Check interval should be at least 10 seconds")
                check_interval = 10
                self.check_interval_var.set("10")

            if update_interval < 100:
                messagebox.showwarning("Warning", "UI update interval should be at least 100ms")
                update_interval = 100
                self.update_interval_var.set("100")

            # Update manager settings
            self.server_manager.server_port = server_port
            self.server_manager.rcon_enabled = rcon_enabled
            self.server_manager.rcon_host = rcon_host
            self.server_manager.rcon_port = rcon_port
            self.server_manager.rcon_password = rcon_password
            self.server_manager.inactivity_timeout = inactivity_timeout
            self.server_manager.check_interval = check_interval
            self.server_manager.debug_mode = debug_mode

            # Update GUI settings
            self.update_interval = update_interval
            self.max_log_lines = max_log_lines

            # Update theme if changed
            if theme != self.theme_name:
                self.theme_name = theme
                self.theme_manager.apply_theme(theme)

            # Update config
            self.server_manager.config.set('Server', 'port', str(server_port))
            self.server_manager.config.set('RCON', 'enabled', str(rcon_enabled))
            self.server_manager.config.set('RCON', 'host', rcon_host)
            self.server_manager.config.set('RCON', 'port', str(rcon_port))
            self.server_manager.config.set('RCON', 'password', rcon_password)
            self.server_manager.config.set('Server', 'inactivity_timeout', str(inactivity_timeout))
            self.server_manager.config.set('Server', 'check_interval', str(check_interval))
            self.server_manager.config.set('GUI', 'update_interval', str(update_interval))
            self.server_manager.config.set('GUI', 'max_log_lines', str(max_log_lines))
            self.server_manager.config.set('GUI', 'theme', theme)
            self.server_manager.config.set('System', 'debug_mode', str(debug_mode))

            # Save config
            from .config import save_config
            save_config(self.server_manager.config)

            messagebox.showinfo("Success", "Application settings saved successfully")
            self.status_bar.config(text="Application settings saved")

            # Server needs to be restarted for some settings to take effect
            if self.server_manager.is_server_running():
                messagebox.showinfo("Settings", "Some settings will take effect after server restart")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save application settings: {e}")

    def on_browse_java(self):
        """Browse for Java executable"""
        file_path = filedialog.askopenfilename(
            title="Select Java Executable",
            filetypes=[
                ("Java Executable", "java.exe java jar"),
                ("All Files", "*.*")
            ]
        )
        if file_path:
            self.java_path_var.set(file_path)

    def on_browse_backup_dir(self):
        """Browse for backup directory"""
        dir_path = filedialog.askdirectory(
            title="Select Backup Directory"
        )
        if dir_path:
            self.backup_dir_var.set(dir_path)

    def on_clear_logs(self):
        """Clear log display"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.status_bar.config(text="Logs cleared")

    def on_export_logs(self):
        """Export logs to a file"""
        file_path = filedialog.asksaveasfilename(
            title="Export Logs",
            defaultextension=".log",
            filetypes=[
                ("Log Files", "*.log"),
                ("Text Files", "*.txt"),
                ("All Files", "*.*")
            ]
        )
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(self.log_text.get(1.0, tk.END))
                self.status_bar.config(text=f"Logs exported to {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export logs: {e}")

    def on_timeframe_change(self, event):
        """Handle timeframe selection change"""
        timeframe = self.timeframe_var.get()
        if timeframe == "15 minutes":
            hours = 0.25
        elif timeframe == "1 hour":
            hours = 1
        elif timeframe == "6 hours":
            hours = 6
        elif timeframe == "24 hours":
            hours = 24
        else:
            hours = 1

        # Get performance history
        history = self.server_manager.performance_monitor.get_history(timeframe_hours=hours)
        if history:
            # Update history data
            self.ram_history = history['ram']
            self.cpu_history = history['cpu']
            self.tps_history = history['tps']
            self.time_labels = history['formatted_times']

            # Update graphs
            self.update_performance_graphs()

        self.status_bar.config(text=f"Showing performance data for the last {timeframe}")

    def on_refresh_graphs(self):
        """Refresh performance graphs"""
        timeframe = self.timeframe_var.get()
        if timeframe == "15 minutes":
            hours = 0.25
        elif timeframe == "1 hour":
            hours = 1
        elif timeframe == "6 hours":
            hours = 6
        elif timeframe == "24 hours":
            hours = 24
        else:
            hours = 1

        # Get performance history
        history = self.server_manager.performance_monitor.get_history(timeframe_hours=hours)
        if history:
            # Update history data
            self.ram_history = history['ram']
            self.cpu_history = history['cpu']
            self.tps_history = history['tps']
            self.time_labels = history['formatted_times']

            # Update graphs
            self.update_performance_graphs()

        self.status_bar.config(text="Performance graphs refreshed")

    def on_view_player(self):
        """View details for the selected player"""
        selected = self.players_tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select a player to view")
            return

        values = self.players_tree.item(selected[0])['values']
        if len(values) < 4:
            messagebox.showinfo("Info", "Player information not available")
            return

        player_name = values[0]
        player_uuid = values[1]
        player_ip = values[2]
        player_time = values[3]

        # Create details dialog
        details_dialog = tk.Toplevel(self.root)
        details_dialog.title(f"Player Details: {player_name}")
        details_dialog.geometry("400x300")
        details_dialog.transient(self.root)
        details_dialog.grab_set()

        ttk.Label(details_dialog, text=player_name, font=("TkDefaultFont", 14, "bold")).pack(padx=10, pady=10)

        details_frame = ttk.Frame(details_dialog)
        details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(details_frame, text="UUID:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_uuid).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(details_frame, text="IP Address:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_ip).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(details_frame, text="Online Time:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        ttk.Label(details_frame, text=player_time).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # If server is running, fetch more details
        if self.server_manager.get_state() == ServerState.RUNNING:
            # Fetch player stats like health, position, etc.
            self.server_manager.get_player_info(player_name,
                                           lambda task: self.update_player_info(task, details_frame))

        ttk.Button(details_dialog, text="Close", command=details_dialog.destroy).pack(pady=10)

    def update_player_info(self, task, details_frame):
        """Update player info in the details dialog"""
        if task.error:
            ttk.Label(details_frame, text="Failed to fetch additional details",
                    foreground="red").grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="w")
            return

        info = task.result
        if not info:
            return

        row = 3
        for key, value in info.items():
            ttk.Label(details_frame, text=f"{key}:").grid(row=row, column=0, padx=5, pady=5, sticky="w")
            ttk.Label(details_frame, text=str(value)).grid(row=row, column=1, padx=5, pady=5, sticky="w")
            row += 1


    def on_close(self):
        """Handle window close event"""
        # Ask for confirmation if server is running
        if self.server_manager.is_server_running():
            result = messagebox.askyesnocancel("Confirm",
                                "Server is running. What would you like to do?\n\n"
                                "• Yes: Stop the server and exit\n"
                                "• No: Exit without stopping the server\n"
                                "• Cancel: Don't exit")

            if result is None:  # Cancel
                return
            elif result:  # Yes - stop server and exit
                self.status_bar.config(text="Stopping server and shutting down...")
                self.root.update_idletasks()  # Force UI update

                # Stop the server and wait for it to complete
                stop_task = self.server_manager.stop_server()

                # Wait for the task to complete (with timeout)
                timeout = time.time() + 30  # 30 second timeout
                while not stop_task.completed and time.time() < timeout:
                    self.root.update()  # Keep UI responsive
                    time.sleep(0.1)

                # Force a more aggressive shutdown
                self._force_exit()
                return
            # If No was selected, we'll fall through to normal shutdown
        else:
            # If server is not running, just ask for confirmation
            if not messagebox.askyesno("Confirm", "Are you sure you want to exit?"):
                return

        # Normal shutdown sequence
        self._force_exit()

    def _force_exit(self):
        """Force exit of the application"""
        logging.info("Forcing application shutdown")

        # Cancel update timers
        if self.status_update_id:
            self.root.after_cancel(self.status_update_id)

        if self.log_update_id:
            self.root.after_cancel(self.log_update_id)

        # Stop all threads
        self.server_manager.stop_all_threads()

        # Destroy window
        self.root.destroy()

        # Directly invoke os._exit instead of scheduling it
        logging.info("Application exit")
        os._exit(0)

    def run(self):
        """Start the GUI main loop"""
        self.root.mainloop()