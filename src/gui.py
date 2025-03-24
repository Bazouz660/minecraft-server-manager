"""
GUI implementation for Minecraft Server Manager
"""

import os
import sys
import time
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import logging
import threading
import traceback

# Internal imports
from .utils import ServerState, TaskType, log_exception

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
    """GUI for the Minecraft server manager"""

    def __init__(self, server_manager):
        self.server_manager = server_manager

        # Load configuration
        self.config = server_manager.config
        self.auto_scroll_logs = self.config.getboolean('GUI', 'auto_scroll_logs')
        self.update_interval = self.config.getint('GUI', 'update_interval')
        self.max_log_lines = self.config.getint('GUI', 'max_log_lines')

        # Create the main window
        self.root = tk.Tk()
        self.root.title(f"Minecraft Server Manager")
        self.root.geometry("700x500")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Variables
        self.status_var = tk.StringVar(value="Offline")
        self.player_count_var = tk.StringVar(value="0")
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.log_queue = queue.Queue()

        # Set server manager callbacks
        self.server_manager.on_state_change = self.on_state_change
        self.server_manager.on_player_count_change = self.on_player_count_change

        # Create custom log handler
        self.log_handler = TextHandler(self.log_queue)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(self.log_handler)

        # Create GUI elements
        self.create_widgets()

        # Update timer IDs
        self.status_update_id = None
        self.log_update_id = None

        # Start update timers
        self.update_status()
        self.update_logs()

        # Start the listener if server is not already running
        if not self.server_manager.is_server_running():
            self.server_manager.start_port_listener()

    def create_widgets(self):
        """Create all GUI elements"""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="Server Status")
        status_frame.pack(fill=tk.X, padx=5, pady=5)

        # Status display
        ttk.Label(status_frame, text="Status:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, width=15)
        self.status_label.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(status_frame, text="Players:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        ttk.Label(status_frame, textvariable=self.player_count_var, width=5).grid(row=0, column=3, padx=5, pady=5, sticky="w")

        ttk.Label(status_frame, text="Uptime:").grid(row=0, column=4, padx=5, pady=5, sticky="w")
        ttk.Label(status_frame, textvariable=self.uptime_var, width=10).grid(row=0, column=5, padx=5, pady=5, sticky="w")

        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        self.start_button = ttk.Button(button_frame, text="Start Server", command=self.on_start)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(button_frame, text="Stop Server", command=self.on_stop)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.restart_button = ttk.Button(button_frame, text="Restart Server", command=self.on_restart)
        self.restart_button.pack(side=tk.LEFT, padx=5)

        # Spacer
        ttk.Frame(button_frame).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Settings button
        self.settings_button = ttk.Button(button_frame, text="Settings", command=self.on_settings)
        self.settings_button.pack(side=tk.RIGHT, padx=5)

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=self.auto_scroll_logs)
        self.auto_scroll_check = ttk.Checkbutton(
            button_frame,
            text="Auto-scroll",
            variable=self.auto_scroll_var
        )
        self.auto_scroll_check.pack(side=tk.RIGHT, padx=5)

        # Log area in a notebook
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Logs tab
        log_frame = ttk.Frame(self.notebook)
        self.notebook.add(log_frame, text="Logs")

        # Log text area
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, background="#f0f0f0")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Set up text tags for log levels
        self.log_text.tag_config("DEBUG", foreground="gray")
        self.log_text.tag_config("INFO", foreground="black")
        self.log_text.tag_config("WARNING", foreground="orange")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("CRITICAL", foreground="red", font=("TkDefaultFont", 10, "bold"))

        # About tab
        about_frame = ttk.Frame(self.notebook)
        self.notebook.add(about_frame, text="About")

        # About text
        from .utils import VERSION
        about_text = f"""
        Minecraft Wake-on-Demand Server Manager v{VERSION}

        This application manages your Minecraft server by:
        • Starting the server when players try to connect
        • Monitoring player activity
        • Shutting down the server after a period of inactivity

        Created by Claude AI
        """
        about_label = ttk.Label(about_frame, text=about_text, wraplength=600, justify="center")
        about_label.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def update_status(self):
        """Update the status display"""
        try:
            # Update UI based on current state
            server_state = self.server_manager.get_state()

            # Update status text and color
            self.status_var.set(server_state.name)

            if server_state == ServerState.OFFLINE:
                self.status_label.config(foreground="red")
                self.player_count_var.set("0")
                self.uptime_var.set("00:00:00")

                # Enable/disable buttons
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                self.restart_button.config(state=tk.NORMAL)

                # Make sure listener is running but don't spam it
                if not self.server_manager.port_listener_thread or not self.server_manager.port_listener_thread.is_alive():
                    self.server_manager.start_port_listener()

            elif server_state == ServerState.STARTING:
                self.status_label.config(foreground="orange")

                # Update elapsed time since starting
                if self.server_manager.start_time > 0:
                    elapsed = int(time.time() - self.server_manager.start_time)
                    self.status_bar.config(text=f"Starting server... ({elapsed}s)")

                # Enable/disable buttons
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.restart_button.config(state=tk.DISABLED)

            elif server_state == ServerState.RUNNING:
                self.status_label.config(foreground="green")

                # Update uptime
                uptime_secs = int(time.time() - self.server_manager.start_time)
                hours, remainder = divmod(uptime_secs, 3600)
                minutes, seconds = divmod(remainder, 60)
                self.uptime_var.set(f"{hours:02}:{minutes:02}:{seconds:02}")

                # Get player count (non-blocking)
                self.server_manager.get_player_count(self.on_player_count_result)

                # Enable/disable buttons
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.restart_button.config(state=tk.NORMAL)

            elif server_state == ServerState.STOPPING:
                self.status_label.config(foreground="orange")

                # Enable/disable buttons
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.DISABLED)
                self.restart_button.config(state=tk.DISABLED)

            # Periodically check server status in the background (non-blocking)
            if server_state in [ServerState.RUNNING, ServerState.STARTING]:
                self.server_manager.queue_task(TaskType.CHECK_STATUS, self.on_status_check_result)

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

    def add_log_message(self, record):
        """Add a log message to the log text area"""
        try:
            # Get the log level tag
            tag = record.levelname

            # Add the message to the text widget
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, record.message + "\n", tag)

            # Limit the number of lines
            num_lines = int(self.log_text.index(tk.END).split('.')[0]) - 1
            if num_lines > self.max_log_lines:
                self.log_text.delete(1.0, f"{num_lines - self.max_log_lines + 1}.0")

            # Auto-scroll if enabled
            if self.auto_scroll_var.get():
                self.log_text.see(tk.END)

            self.log_text.configure(state=tk.DISABLED)
        except Exception as e:
            print(f"Error adding log message: {e}")

    def on_state_change(self, old_state, new_state):
        """Callback for server state changes"""
        # Update status bar
        if new_state == ServerState.STARTING:
            self.status_bar.config(text="Server is starting...")
        elif new_state == ServerState.RUNNING:
            self.status_bar.config(text="Server is running")
        elif new_state == ServerState.STOPPING:
            self.status_bar.config(text="Server is stopping...")
        elif new_state == ServerState.OFFLINE:
            self.status_bar.config(text="Server is offline")

    def on_player_count_change(self, count):
        """Callback for player count changes"""
        self.player_count_var.set(str(count))

    def on_player_count_result(self, task):
        """Callback for player count task completion"""
        if task.error:
            # Don't log this as it's a frequent operation
            return

        count = task.result
        if count is not None:
            self.player_count_var.set(str(count))

    def on_status_check_result(self, task):
        """Callback for server status check task"""
        # We don't need to do anything here as the server manager
        # will update its state and call our state change callback
        pass

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
        """Settings button handler"""
        # Create settings dialog
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("500x400")
        settings_window.transient(self.root)
        settings_window.grab_set()

        # Create notebook for settings tabs
        settings_notebook = ttk.Notebook(settings_window)
        settings_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Server settings tab
        server_frame = ttk.Frame(settings_notebook)
        settings_notebook.add(server_frame, text="Server")

        # Server settings
        ttk.Label(server_frame, text="Server Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        port_var = tk.StringVar(value=str(self.server_manager.server_port))
        port_entry = ttk.Entry(server_frame, textvariable=port_var, width=8)
        port_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(server_frame, text="Start Command:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        start_command_var = tk.StringVar(value=self.server_manager.start_command)
        start_command_entry = ttk.Entry(server_frame, textvariable=start_command_var, width=30)
        start_command_entry.grid(row=1, column=1, columnspan=3, padx=5, pady=5, sticky="w")

        # Timeouts tab
        timeouts_frame = ttk.Frame(settings_notebook)
        settings_notebook.add(timeouts_frame, text="Timeouts")

        ttk.Label(timeouts_frame, text="Inactivity Timeout (seconds):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        inactivity_var = tk.StringVar(value=str(self.server_manager.inactivity_timeout))
        inactivity_entry = ttk.Entry(timeouts_frame, textvariable=inactivity_var, width=8)
        inactivity_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(timeouts_frame, text="Check Interval (seconds):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        check_interval_var = tk.StringVar(value=str(self.server_manager.check_interval))
        check_interval_entry = ttk.Entry(timeouts_frame, textvariable=check_interval_var, width=8)
        check_interval_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # RCON settings tab
        rcon_frame = ttk.Frame(settings_notebook)
        settings_notebook.add(rcon_frame, text="RCON")

        rcon_enabled_var = tk.BooleanVar(value=self.server_manager.rcon_enabled)
        rcon_enabled_check = ttk.Checkbutton(rcon_frame, text="Enable RCON", variable=rcon_enabled_var)
        rcon_enabled_check.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Host:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        rcon_host_var = tk.StringVar(value=self.server_manager.rcon_host)
        rcon_host_entry = ttk.Entry(rcon_frame, textvariable=rcon_host_var, width=20)
        rcon_host_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Port:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        rcon_port_var = tk.StringVar(value=str(self.server_manager.rcon_port))
        rcon_port_entry = ttk.Entry(rcon_frame, textvariable=rcon_port_var, width=8)
        rcon_port_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(rcon_frame, text="RCON Password:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        rcon_password_var = tk.StringVar(value=self.server_manager.rcon_password)
        rcon_password_entry = ttk.Entry(rcon_frame, textvariable=rcon_password_var, width=20, show="*")
        rcon_password_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")

        # GUI settings tab
        gui_frame = ttk.Frame(settings_notebook)
        settings_notebook.add(gui_frame, text="GUI")

        ttk.Label(gui_frame, text="Update Interval (ms):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        update_interval_var = tk.StringVar(value=str(self.update_interval))
        update_interval_entry = ttk.Entry(gui_frame, textvariable=update_interval_var, width=8)
        update_interval_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(gui_frame, text="Max Log Lines:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        max_log_lines_var = tk.StringVar(value=str(self.max_log_lines))
        max_log_lines_entry = ttk.Entry(gui_frame, textvariable=max_log_lines_var, width=8)
        max_log_lines_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        debug_mode_var = tk.BooleanVar(value=self.server_manager.debug_mode)
        debug_mode_check = ttk.Checkbutton(gui_frame, text="Debug Mode", variable=debug_mode_var)
        debug_mode_check.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Buttons frame
        buttons_frame = ttk.Frame(settings_window)
        buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        def save_settings():
            """Save settings to configuration"""
            try:
                # Update server settings
                self.server_manager.server_port = int(port_var.get())
                self.server_manager.start_command = start_command_var.get()
                self.server_manager.inactivity_timeout = int(inactivity_var.get())
                self.server_manager.check_interval = int(check_interval_var.get())

                # Update RCON settings
                from .utils import RCON_AVAILABLE
                self.server_manager.rcon_enabled = rcon_enabled_var.get() and RCON_AVAILABLE
                self.server_manager.rcon_host = rcon_host_var.get()
                self.server_manager.rcon_port = int(rcon_port_var.get())
                self.server_manager.rcon_password = rcon_password_var.get()

                # Update GUI settings
                self.update_interval = int(update_interval_var.get())
                self.max_log_lines = int(max_log_lines_var.get())

                # Update debug mode
                self.server_manager.debug_mode = debug_mode_var.get()

                # Update configuration
                self.server_manager.config.set('Server', 'port', port_var.get())
                self.server_manager.config.set('Server', 'start_command', start_command_var.get())
                self.server_manager.config.set('Server', 'inactivity_timeout', inactivity_var.get())
                self.server_manager.config.set('Server', 'check_interval', check_interval_var.get())

                self.server_manager.config.set('RCON', 'enabled', str(rcon_enabled_var.get()))
                self.server_manager.config.set('RCON', 'host', rcon_host_var.get())
                self.server_manager.config.set('RCON', 'port', rcon_port_var.get())
                self.server_manager.config.set('RCON', 'password', rcon_password_var.get())

                self.server_manager.config.set('GUI', 'update_interval', update_interval_var.get())
                self.server_manager.config.set('GUI', 'max_log_lines', max_log_lines_var.get())

                self.server_manager.config.set('System', 'debug_mode', str(debug_mode_var.get()))

                # Save configuration
                from .config import save_config
                save_config(self.server_manager.config)

                # Close dialog
                settings_window.destroy()

                # Show confirmation
                messagebox.showinfo("Settings", "Settings saved successfully")

                # Note: Server needs to be restarted for some settings to take effect
                if self.server_manager.is_server_running():
                    messagebox.showinfo("Settings", "Some settings will take effect after server restart")

            except Exception as e:
                log_exception(e, self.server_manager.debug_mode)
                messagebox.showerror("Error", f"Failed to save settings: {e}")

        # Save button
        save_button = ttk.Button(buttons_frame, text="Save", command=save_settings)
        save_button.pack(side=tk.RIGHT, padx=5)

        # Cancel button
        cancel_button = ttk.Button(buttons_frame, text="Cancel", command=settings_window.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

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