"""
Enhanced server management for Minecraft Server Manager
"""

import os
import sys
import time
import socket
import subprocess
import threading
import logging
import queue
import re
import shutil
import zipfile
import traceback
from datetime import datetime

# Internal imports
from .utils import ServerState, TaskType, Task, log_exception, VERSION
from .minecraft_protocol import MinecraftProtocol
from .minecraft_status import MinecraftStatusProtocol
from .performance_monitor import PerformanceMonitor
from .server_properties import ServerPropertiesManager


# Check for mcrcon
try:
    from mcrcon import MCRcon
    RCON_AVAILABLE = True
except ImportError:
    RCON_AVAILABLE = False
    logging.warning("MCRCON not available. Install with: pip install mcrcon")

# Check for psutil (for performance monitoring)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available. Performance monitoring will be limited. Install with: pip install psutil")

class EnhancedServerManager:
    """Enhanced version of the Minecraft server manager with additional features"""

    def __init__(self, config):
        """Initialize the server manager with the given configuration"""
        self.config = config

        # Server info
        self.server_port = config.getint('Server', 'port')
        self.start_command = config.get('Server', 'start_command')
        self.inactivity_timeout = config.getint('Server', 'inactivity_timeout')
        self.check_interval = config.getint('Server', 'check_interval')
        self.startup_wait = config.getint('Server', 'startup_wait')
        self.shutdown_timeout = config.getint('Server', 'shutdown_timeout')

        # RCON settings
        self.rcon_enabled = RCON_AVAILABLE and config.getboolean('RCON', 'enabled')
        if self.rcon_enabled:
            self.rcon_host = config.get('RCON', 'host')
            self.rcon_port = config.getint('RCON', 'port')
            self.rcon_password = config.get('RCON', 'password')
            self.rcon_timeout = config.getint('RCON', 'timeout')

        # Debug mode
        self.debug_mode = config.getboolean('System', 'debug_mode')

        # State variables and synchronization
        self.state_lock = threading.RLock()
        self.state = ServerState.OFFLINE
        self.process = None
        self.start_time = 0
        self.player_count = 0

        # Server details
        self.server_version = "Unknown"
        self.server_motd = "Unknown"
        self.max_players = 0
        self.online_players = []

        # Thread control
        self.stop_event = threading.Event()
        self.port_listener_thread = None
        self.monitor_thread = None
        self.worker_thread = None
        self.task_queue = queue.Queue()

        # Event callbacks
        self.on_state_change = None
        self.on_player_count_change = None
        self.on_log_message = None
        self.on_status_update = None

        # Performance monitor
        self.performance_monitor = PerformanceMonitor(self)

        # Server properties manager
        self.properties_manager = ServerPropertiesManager()

        # Start worker thread
        self.worker_thread = threading.Thread(target=self._worker_thread_func, daemon=True)
        self.worker_thread.start()

    def get_state(self):
        """Thread-safe state getter"""
        with self.state_lock:
            return self.state

    def set_state(self, new_state):
        """Thread-safe state setter with callback"""
        old_state = None
        with self.state_lock:
            old_state = self.state
            self.state = new_state

        if old_state != new_state:
            logging.info(f"Server state changed: {old_state.name} -> {new_state.name}")
            if self.on_state_change:
                try:
                    self.on_state_change(old_state, new_state)
                except Exception as e:
                    log_exception(e, self.debug_mode)

    def is_port_in_use(self):
        """
        Check if the server port is in use by something other than our listener
        Returns True only if the port is in use by the actual Minecraft server
        """
        # If we have a process and it's running, we can assume it's using the port
        with self.state_lock:
            if self.process and self.process.poll() is None:
                return True

        # If we're in OFFLINE state and have an active listener,
        # the port is in use by our listener, not the Minecraft server
        if self.get_state() == ServerState.OFFLINE and self.port_listener_thread and self.port_listener_thread.is_alive():
            return False

        # Otherwise, check if something is using the port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(1)
                s.connect(("localhost", self.server_port))
                return True
            except:
                return False

    def is_server_running(self):
        """Check if server is running"""
        # First check if we have a process and it's still running
        with self.state_lock:
            if self.process and self.process.poll() is None:
                return True

        # Then check if the port is in use
        if self.is_port_in_use():
            return True

        return False

    def queue_task(self, task_type, callback=None, **kwargs):
        """Add a task to the worker queue"""
        task = Task(task_type, callback, **kwargs)
        self.task_queue.put(task)
        return task

    def start_server(self, callback=None):
        """Queue a task to start the server"""
        return self.queue_task(TaskType.START_SERVER, callback)

    def stop_server(self, callback=None):
        """Queue a task to stop the server"""
        return self.queue_task(TaskType.STOP_SERVER, callback)

    def restart_server(self, callback=None):
        """Queue a task to restart the server"""
        return self.queue_task(TaskType.RESTART_SERVER, callback)

    def get_player_count(self, callback=None):
        """Queue a task to get the player count"""
        return self.queue_task(TaskType.GET_PLAYERS, callback)

    def get_detailed_status(self, callback=None):
        """Queue a task to get detailed server status"""
        return self.queue_task(TaskType.GET_STATUS, callback)

    def get_performance_data(self, callback=None):
        """Queue a task to get performance data"""
        return self.queue_task(TaskType.GET_PERFORMANCE, callback)

    def run_command(self, command, callback=None):
        """Queue a task to run a console command"""
        return self.queue_task(TaskType.RUN_COMMAND, callback, command=command)

    def backup_world(self, callback=None):
        """Queue a task to backup the world"""
        return self.queue_task(TaskType.BACKUP_WORLD, callback)

    def load_properties(self, callback=None):
        """Queue a task to load server properties"""
        return self.queue_task(TaskType.LOAD_PROPERTIES, callback)

    def save_properties(self, properties, callback=None):
        """Queue a task to save server properties"""
        return self.queue_task(TaskType.SAVE_PROPERTIES, callback, properties=properties)

    def update_java_settings(self, min_memory, max_memory, jvm_args, callback=None):
        """Queue a task to update Java settings"""
        return self.queue_task(TaskType.UPDATE_JAVA_SETTINGS, callback,
                           min_memory=min_memory, max_memory=max_memory, jvm_args=jvm_args)

    def get_player_info(self, player_name, callback=None):
        """Queue a task to get player information"""
        return self.queue_task(TaskType.GET_PLAYER_INFO, callback, player_name=player_name)


    def get_detailed_status(self, callback=None):
        """Queue a task to get detailed server status"""
        return self.queue_task(TaskType.GET_STATUS, callback)

    def get_performance_data(self, callback=None):
        """Queue a task to get performance data"""
        return self.queue_task(TaskType.GET_PERFORMANCE, callback)

    def run_command(self, command, callback=None):
        """Queue a task to run a console command"""
        return self.queue_task(TaskType.RUN_COMMAND, callback, command=command)

    def backup_world(self, callback=None):
        """Queue a task to backup the world"""
        return self.queue_task(TaskType.BACKUP_WORLD, callback)

    def load_properties(self, callback=None):
        """Queue a task to load server properties"""
        return self.queue_task(TaskType.LOAD_PROPERTIES, callback)

    def save_properties(self, properties, callback=None):
        """Queue a task to save server properties"""
        return self.queue_task(TaskType.SAVE_PROPERTIES, callback, properties=properties)

    def update_java_settings(self, min_memory, max_memory, jvm_args, callback=None):
        """Queue a task to update Java settings"""
        return self.queue_task(TaskType.UPDATE_JAVA_SETTINGS, callback,
                        min_memory=min_memory, max_memory=max_memory, jvm_args=jvm_args)

    def get_player_info(self, player_name, callback=None):
        """Queue a task to get player information"""
        return self.queue_task(TaskType.GET_PLAYER_INFO, callback, player_name=player_name)

    def start_port_listener(self):
        """Start listening for incoming connections to wake up the server"""
        if self.port_listener_thread and self.port_listener_thread.is_alive():
            logging.debug("Port listener thread already running")
            return  # Already listening

        # If we already have a thread but it's not alive, reset it
        if self.port_listener_thread:
            self.port_listener_thread = None

        # Only start listening if the server is not running
        if self.get_state() in [ServerState.RUNNING, ServerState.STARTING]:
            logging.debug("Not starting port listener because server is already running")
            return

        # Clear stop event
        self.stop_event.clear()

        # Start the thread
        self.port_listener_thread = threading.Thread(
            target=self._port_listener_thread,
            daemon=True
        )
        self.port_listener_thread.start()
        logging.info("Port listener thread started")

    def start_monitoring(self):
        """Start monitoring for player inactivity"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return  # Already monitoring

        self.monitor_thread = threading.Thread(
            target=self._monitor_thread,
            daemon=True
        )
        self.monitor_thread.start()

    def stop_all_threads(self):
        """Signal all threads to stop"""
        logging.info("Stopping all background threads")

        # Set stop event to signal threads to stop
        self.stop_event.set()

        # Wait briefly for threads to notice the signal
        time.sleep(0.5)

        # Unblock socket operations with a self-connection
        self._unblock_listener_socket()

        # Clean up performance monitor
        self.performance_monitor.cleanup()

    def _unblock_listener_socket(self):
        """Create a dummy connection to unblock any listening socket"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                try:
                    s.connect(('127.0.0.1', self.server_port))
                except:
                    pass
        except:
            pass

    def _worker_thread_func(self):
        """Background thread that processes tasks from the queue"""
        logging.info("Worker thread started")

        while not self.stop_event.is_set():
            try:
                # Get a task from the queue with timeout
                try:
                    task = self.task_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Process the task
                try:
                    if task.type == TaskType.START_SERVER:
                        task.result = self._start_server_impl()
                    elif task.type == TaskType.STOP_SERVER:
                        task.result = self._stop_server_impl()
                    elif task.type == TaskType.RESTART_SERVER:
                        task.result = self._restart_server_impl()
                    elif task.type == TaskType.GET_PLAYERS:
                        task.result = self._get_player_count_impl()
                    elif task.type == TaskType.CHECK_STATUS:
                        task.result = self._check_status_impl()
                    elif task.type == TaskType.GET_STATUS:
                        task.result = self._get_detailed_status_impl()
                    elif task.type == TaskType.GET_PERFORMANCE:
                        task.result = self._get_performance_impl()
                    elif task.type == TaskType.RUN_COMMAND:
                        task.result = self._run_command_impl(task.args.get('command', ''))
                    elif task.type == TaskType.BACKUP_WORLD:
                        task.result = self._backup_world_impl()
                    elif task.type == TaskType.LOAD_PROPERTIES:
                        task.result = self._load_properties_impl()
                    elif task.type == TaskType.SAVE_PROPERTIES:
                        task.result = self._save_properties_impl(task.args.get('properties', {}))
                    elif task.type == TaskType.UPDATE_JAVA_SETTINGS:
                        task.result = self._update_java_settings_impl(
                            task.args.get('min_memory', 1024),
                            task.args.get('max_memory', 4096),
                            task.args.get('jvm_args', '')
                        )
                    elif task.type == TaskType.GET_PLAYER_INFO:
                        task.result = self._get_player_info_impl(task.args.get('player_name', ''))
                    elif task.type == TaskType.GET_STATUS:
                        task.result = self._get_detailed_status_impl()
                    elif task.type == TaskType.GET_PERFORMANCE:
                        task.result = self._get_performance_impl()
                    elif task.type == TaskType.RUN_COMMAND:
                        task.result = self._run_command_impl(task.args.get('command', ''))
                    elif task.type == TaskType.BACKUP_WORLD:
                        task.result = self._backup_world_impl()
                    elif task.type == TaskType.LOAD_PROPERTIES:
                        task.result = self._load_properties_impl()
                    elif task.type == TaskType.SAVE_PROPERTIES:
                        task.result = self._save_properties_impl(task.args.get('properties', {}))
                    elif task.type == TaskType.UPDATE_JAVA_SETTINGS:
                        task.result = self._update_java_settings_impl(
                            task.args.get('min_memory', 1024),
                            task.args.get('max_memory', 4096),
                            task.args.get('jvm_args', '')
                        )
                    elif task.type == TaskType.GET_PLAYER_INFO:
                        task.result = self._get_player_info_impl(task.args.get('player_name', ''))
                    else:
                        logging.warning(f"Unknown task type: {task.type}")
                except Exception as e:
                    log_exception(e, self.debug_mode)
                    task.error = str(e)

                # Mark task as completed
                task.completed = True

                # Execute callback if provided
                if task.callback:
                    try:
                        task.callback(task)
                    except Exception as e:
                        log_exception(e, self.debug_mode)

                # Mark task as done in the queue
                self.task_queue.task_done()

            except Exception as e:
                log_exception(e, self.debug_mode)

        logging.info("Worker thread exiting")

    def _start_server_impl(self):
        """Implementation of server start logic"""
        if self.is_server_running():
            logging.info("Server is already running")
            return True

        # Change state to starting
        self.set_state(ServerState.STARTING)
        logging.info(f"Starting Minecraft server using '{self.start_command}'")

        try:
            # Make sure any existing port listener is stopped
            self.stop_event.set()
            if self.port_listener_thread and self.port_listener_thread.is_alive():
                # Wait briefly for the thread to notice the stop event
                self.port_listener_thread.join(timeout=2)
                if self.port_listener_thread.is_alive():
                    logging.warning("Port listener thread didn't terminate gracefully")

            # Reset stop event for other threads
            self.stop_event.clear()

            # Wait a moment to ensure the port is free
            time.sleep(1)

            # Launch in new window on Windows
            if sys.platform == 'win32':
                # Use START command to open in a new console window with a title
                self.process = subprocess.Popen(
                    f'start "Minecraft Server" /WAIT {self.start_command}',
                    shell=True
                )
            else:
                # On other platforms, just run the command
                self.process = subprocess.Popen(
                    self.start_command,
                    shell=True
                )

            # Store start time
            self.start_time = time.time()

            # Wait briefly for the server to start
            logging.info(f"Waiting {self.startup_wait} seconds for initial server startup...")
            time.sleep(self.startup_wait)

            # Check if process is still running
            if self.process and self.process.poll() is None:
                logging.info("Server process started successfully")
            else:
                logging.error("Server process failed to start or terminated immediately")
                self.set_state(ServerState.OFFLINE)
                return False

            # Stay in STARTING state until the server responds to ping
            # The status checker will update to RUNNING when appropriate

            # Start monitoring thread
            self.start_monitoring()

            return True
        except Exception as e:
            log_exception(e, self.debug_mode)
            self.set_state(ServerState.OFFLINE)
            return False

    def _stop_server_impl(self):
        """Implementation of server stop logic"""
        if not self.is_server_running():
            logging.info("Server is not running")
            self.set_state(ServerState.OFFLINE)
            return True

        self.set_state(ServerState.STOPPING)
        logging.info("Stopping Minecraft server")

        stop_success = False

        # Try RCON first if enabled
        if self.rcon_enabled:
            try:
                with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                    logging.info("Connected to RCON for stopping")
                    mcr.command("say Server is shutting down...")
                    mcr.command("stop")

                    # Wait for process to terminate
                    deadline = time.time() + self.shutdown_timeout
                    while time.time() < deadline:
                        if not self.is_server_running():
                            stop_success = True
                            break
                        time.sleep(1)
            except Exception as e:
                log_exception(e, self.debug_mode)

        # Force kill if still running
        if not stop_success and self.is_server_running():
            if self.process:
                try:
                    logging.warning("Using force termination of server process")

                    # On Windows use taskkill to ensure all child processes are terminated
                    if sys.platform == 'win32':
                        try:
                            # Try to get the process ID
                            pid = self.process.pid
                            logging.info(f"Terminating process tree with PID {pid}")

                            # Use taskkill to terminate the entire process tree
                            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True)
                            stop_success = True
                        except Exception as e:
                            log_exception(e, self.debug_mode)
                    else:
                        # On other platforms, just terminate the process
                        self.process.terminate()

                    # Wait for process to terminate
                    try:
                        self.process.wait(timeout=10)
                        stop_success = True
                    except subprocess.TimeoutExpired:
                        logging.error("Process did not terminate after 10 seconds")

                        # Last resort: kill
                        if sys.platform != 'win32':  # kill() doesn't work well on Windows
                            logging.warning("Sending SIGKILL to server process")
                            try:
                                self.process.kill()
                                self.process.wait(timeout=5)
                                stop_success = True
                            except Exception as e:
                                log_exception(e, self.debug_mode)
                except Exception as e:
                    log_exception(e, self.debug_mode)

        # Final check to see if server is actually stopped
        if not self.is_server_running():
            stop_success = True

        # Reset state
        self.set_state(ServerState.OFFLINE)
        self.process = None

        # Start listening for connections again
        self.start_port_listener()

        return stop_success

    def _restart_server_impl(self):
        """Implementation of server restart logic"""
        logging.info("Restarting Minecraft server")

        # First stop the server
        stop_result = self._stop_server_impl()
        if not stop_result:
            logging.warning("Server stop failed during restart")

        # Wait a moment for resources to be released
        time.sleep(5)

        # Start the server again
        return self._start_server_impl()

    def _get_player_count_impl(self):
        """Implementation of player count retrieval"""
        if not self.is_server_running() or not self.rcon_enabled:
            self.player_count = 0
            return 0

        # Only try RCON if server has been running at least 30 seconds
        if time.time() - self.start_time < 30:
            return self.player_count

        try:
            with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                response = mcr.command("list")
                match = re.search(r"There are (\d+)/\d+ players online", response)
                if match:
                    count = int(match.group(1))

                    # Update count and notify if changed
                    if count != self.player_count:
                        self.player_count = count
                        if self.on_player_count_change:
                            try:
                                self.on_player_count_change(count)
                            except Exception as e:
                                log_exception(e, self.debug_mode)

                    # Parse player list if available
                    if count > 0:
                        player_match = re.search(r"online:(.*)", response)
                        if player_match:
                            player_list_str = player_match.group(1).strip()
                            player_names = [name.strip() for name in player_list_str.split(',')]
                            self.online_players = player_names

                    return count
        except ConnectionRefusedError:
            # This is normal during startup
            logging.debug("RCON connection refused")
        except Exception as e:
            log_exception(e, self.debug_mode)

        return self.player_count

    def _check_status_impl(self):
        """Implementation of server status check"""
        current_state = self.get_state()

        # If we think the server is running, verify that it actually is
        if current_state in [ServerState.RUNNING, ServerState.STARTING]:
            # Check process status
            process_running = self.process and self.process.poll() is None

            if not process_running:
                # Server process is not running
                logging.warning("Server process not found, server may have crashed")
                self.set_state(ServerState.OFFLINE)
                return False

            # Check if the server is actually responding to ping requests
            if current_state == ServerState.RUNNING or (time.time() - self.start_time > 30):
                ping_result = MinecraftProtocol.ping_minecraft_server(port=self.server_port)

                if ping_result == "online":
                    # Server is responding to ping requests
                    if current_state == ServerState.STARTING:
                        logging.info("Server is now fully started and responding to ping requests")
                        self.set_state(ServerState.RUNNING)

                        # Get detailed status
                        self._get_detailed_status_impl()
                    return True
                elif ping_result == "starting":
                    # Server port is open but not responding to ping properly yet
                    logging.info("Server port is open but not responding to ping properly yet")
                    return True
                elif ping_result == "offline" and current_state == ServerState.RUNNING:
                    # Server was running but now seems to be offline
                    logging.warning("Server process exists but is not responding to ping requests")
                    if time.time() - self.start_time > 60:  # If it's been running for more than 60 seconds
                        logging.warning("Server may be frozen or crashed, consider restarting")
                    return True  # Still return True as the process is running

        # If we think the server is offline, check if it's actually running
        elif current_state in [ServerState.OFFLINE, ServerState.STOPPING]:
            # We only want to check if the Minecraft server is running, not our listener
            # So we check if we have a server process running
            process_running = self.process and self.process.poll() is None

            if process_running:
                # We have a server process, but our state says offline
                logging.info("Server process found while status is OFFLINE, updating state to STARTING")
                self.set_state(ServerState.STARTING)
                if self.start_time == 0:
                    self.start_time = time.time()  # Estimate start time
                return True

        # Return True if the state indicates the server is running
        return current_state in [ServerState.RUNNING, ServerState.STARTING]

    def _get_detailed_status_impl(self):
        """Implementation of detailed server status retrieval"""
        if not self.is_server_running():
            return None

        # Get status using enhanced protocol
        status = MinecraftStatusProtocol.query_server_status(host="localhost", port=self.server_port)

        if status:
            # Update server info
            if 'version' in status:
                self.server_version = status['version']

            if 'motd' in status:
                self.server_motd = status['motd']

            if 'players' in status:
                if 'max' in status['players']:
                    self.max_players = status['players']['max']

                if 'online' in status['players']:
                    old_count = self.player_count
                    self.player_count = status['players']['online']

                    # Notify of player count change
                    if old_count != self.player_count and self.on_player_count_change:
                        try:
                            self.on_player_count_change(self.player_count)
                        except Exception as e:
                            log_exception(e, self.debug_mode)

                # Get player list if available
                if 'sample' in status['players']:
                    self.online_players = [player['name'] for player in status['players']['sample']]

            # Get performance data
            performance_data = self._get_performance_impl()
            if performance_data:
                status['performance'] = performance_data

            # Notify of status update
            if self.on_status_update:
                try:
                    self.on_status_update(status)
                except Exception as e:
                    log_exception(e, self.debug_mode)

            return status

        return None

    def _get_performance_impl(self):
        """Implementation of performance data retrieval"""
        if not self.is_server_running():
            return None

        # First try to get performance data from RCON
        performance = MinecraftStatusProtocol.get_performance_data(self)

        # If that fails, try to get process stats
        if not performance and PSUTIL_AVAILABLE:
            performance = self.performance_monitor.get_process_stats()

        if performance:
            # Add to performance history
            self.performance_monitor.add_data_point(
                ram=performance.get('ram', None),
                cpu=performance.get('cpu', None),
                tps=performance.get('tps', None),
                players=self.player_count
            )

        return performance

    def _run_command_impl(self, command):
        """Implementation of running a server command"""
        if not self.is_server_running() or not self.rcon_enabled:
            return "Server is not running or RCON is not enabled"

        try:
            with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                response = mcr.command(command)
                return response
        except Exception as e:
            log_exception(e, self.debug_mode)
            raise Exception(f"Failed to run command: {e}")

    def _backup_world_impl(self):
        """Implementation of world backup"""
        try:
            # Get world name from server.properties
            world_name = "world"  # Default world name
            properties = self.properties_manager.load_properties()
            if properties and 'level-name' in properties:
                if isinstance(properties['level-name'], dict):
                    world_name = properties['level-name']['value']
                else:
                    world_name = properties['level-name']

            # Check if world directory exists
            if not os.path.exists(world_name):
                raise Exception(f"World directory '{world_name}' not found")

            # Create backup directory if it doesn't exist
            backup_dir = "backups"
            os.makedirs(backup_dir, exist_ok=True)

            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"{world_name}_{timestamp}.zip")

            # If server is running, save the world first using RCON
            if self.is_server_running() and self.rcon_enabled:
                try:
                    with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                        logging.info("Saving world...")
                        mcr.command("say Server backup starting, there may be lag...")
                        mcr.command("save-all")
                        time.sleep(5)  # Wait for save to complete
                        mcr.command("save-off")  # Disable saving during backup

                    # Create zip backup
                    logging.info(f"Creating backup of '{world_name}' to '{backup_file}'")
                    with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(world_name):
                            for file in files:
                                file_path = os.path.join(root, file)
                                zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(world_name)))

                    # Re-enable saving
                    if self.is_server_running() and self.rcon_enabled:
                        with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                            mcr.command("save-on")
                            mcr.command("say Server backup complete")

                except Exception as e:
                    # Make sure save is re-enabled even if backup fails
                    try:
                        if self.is_server_running() and self.rcon_enabled:
                            with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                                mcr.command("save-on")
                                mcr.command("say Server backup failed")
                    except:
                        pass
                    raise e
            else:
                # Server is not running, simply zip the world
                logging.info(f"Creating backup of '{world_name}' to '{backup_file}'")
                with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(world_name):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(world_name)))

            logging.info(f"World backup completed: {backup_file}")
            return backup_file

        except Exception as e:
            log_exception(e, self.debug_mode)
            raise Exception(f"Backup failed: {e}")

    def _load_properties_impl(self):
        """Implementation of loading server properties"""
        try:
            properties = self.properties_manager.load_properties()
            return properties
        except Exception as e:
            log_exception(e, self.debug_mode)
            raise Exception(f"Failed to load properties: {e}")

    def _save_properties_impl(self, properties):
        """Implementation of saving server properties"""
        try:
            # If properties is a simplified dictionary, update the full properties
            if properties and all(not isinstance(v, dict) for v in properties.values()):
                self.properties_manager.update_from_simplified(properties)
                result = self.properties_manager.save_properties()
            else:
                # Otherwise, save the full properties dictionary
                result = self.properties_manager.save_properties(properties)

            return result
        except Exception as e:
            log_exception(e, self.debug_mode)
            raise Exception(f"Failed to save properties: {e}")

    def _update_java_settings_impl(self, min_memory, max_memory, jvm_args):
        """Implementation of updating Java settings"""
        try:
            result = self.properties_manager.edit_java_arguments(
                start_script=self.start_command,
                min_memory=min_memory,
                max_memory=max_memory,
                jvm_args=jvm_args
            )
            return result
        except Exception as e:
            log_exception(e, self.debug_mode)
            raise Exception(f"Failed to update Java settings: {e}")

    def _get_player_info_impl(self, player_name):
        """Implementation of getting player information"""
        if not player_name or not self.is_server_running() or not self.rcon_enabled:
            return None

        return MinecraftStatusProtocol.get_player_details(self, player_name)

    def _port_listener_thread(self):
        """Thread function that listens for Minecraft connections and starts server on demand"""
        logging.info(f"Listening for connections on port {self.server_port}")

        # Socket management
        server_socket = None

        # Flag to track if we're actually bound to the port
        socket_bound = False

        try:
            # Create socket
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Try to bind to the port
            retry_count = 0
            while retry_count < 30 and not self.stop_event.is_set():
                try:
                    server_socket.bind(('', self.server_port))
                    server_socket.listen(5)
                    socket_bound = True
                    break
                except OSError:
                    retry_count += 1
                    if retry_count % 5 == 0:  # Log every 5 attempts
                        logging.warning(f"Port {self.server_port} not available, retrying ({retry_count}/30)")
                    time.sleep(1)

            if retry_count >= 30 or self.stop_event.is_set():
                if retry_count >= 30:
                    logging.error(f"Could not bind to port {self.server_port} after 30 attempts")
                return

            # If the server is running, don't listen (this can happen if we detect the server is running
            # after we've already started this thread)
            if self.get_state() in [ServerState.RUNNING, ServerState.STARTING]:
                logging.info("Server is already running, port listener exiting")
                return

            # Set a timeout so we can check the stop event
            server_socket.settimeout(0.5)

            # Main listening loop
            while not self.stop_event.is_set():
                try:
                    # Accept a connection
                    client_socket, addr = server_socket.accept()
                    logging.info(f"Connection from {addr} - checking packet type")

                    # Handle the connection in a separate thread to avoid blocking
                    connection_thread = threading.Thread(
                        target=self._handle_client_connection,
                        args=(client_socket, addr, server_socket),
                        daemon=True
                    )
                    connection_thread.start()

                    # If the server is starting or running, exit this thread
                    if self.get_state() in [ServerState.STARTING, ServerState.RUNNING]:
                        logging.info("Server is now starting or running, port listener exiting")
                        break

                except socket.timeout:
                    # This is normal, just check if we should stop
                    continue
                except ConnectionAbortedError:
                    # This can happen during shutdown
                    if not self.stop_event.is_set():
                        logging.error("Connection aborted unexpectedly")
                    break
                except Exception as e:
                    if not self.stop_event.is_set():
                        log_exception(e, self.debug_mode)
                    time.sleep(1)
        except Exception as e:
            if not self.stop_event.is_set():
                log_exception(e, self.debug_mode)
        finally:
            if socket_bound and server_socket:
                try:
                    server_socket.close()
                    logging.info("Server socket closed")
                except Exception as e:
                    log_exception(e, self.debug_mode)

            logging.info("Port listener thread exiting")

    def _handle_client_connection(self, client_socket, addr, server_socket):
        """Handle an incoming client connection"""
        try:
            # Determine if this is a login attempt or just a ping
            connection_type = MinecraftProtocol.handle_client_connection(client_socket, addr)

            # Close client socket
            try:
                client_socket.close()
            except:
                pass

            if connection_type == "login":
                # This is a login attempt, start the server
                logging.info(f"Login attempt from {addr} - starting server")

                # Close the server socket and set it to None to prevent further use
                try:
                    server_socket.close()
                except:
                    pass

                # Signal the listener thread to stop
                self.stop_event.set()

                # Start the server
                self.start_server()
            else:
                # This is just a ping, continue listening
                logging.debug(f"Status request from {addr} - ignoring")
        except Exception as e:
            log_exception(e, self.debug_mode)

    def _monitor_thread(self):
        """Thread function that monitors for player inactivity"""
        logging.info("Starting player inactivity monitoring")

        # Wait for server to fully start
        time.sleep(30)

        inactive_time = 0

        while not self.stop_event.is_set():
            if not self.is_server_running():
                break

            # Check for players
            player_count = self._get_player_count_impl()

            if player_count == 0:
                inactive_time += self.check_interval
                logging.info(f"No players online. Inactivity: {inactive_time}/{self.inactivity_timeout}s")

                if inactive_time >= self.inactivity_timeout:
                    logging.info("Shutting down server due to inactivity")

                    # Queue the stop task (non-blocking)
                    self.stop_server()
                    break
            else:
                inactive_time = 0
                logging.info(f"{player_count} player(s) online")

            # Sleep in smaller chunks to check stop event more often
            for _ in range(min(self.check_interval, 60)):
                if self.stop_event.is_set() or not self.is_server_running():
                    break
                time.sleep(1)

        logging.info("Monitor thread exiting")

def _get_detailed_status_impl(self):
    """Implementation of detailed status retrieval"""
    if not self.is_server_running():
        return None

    # Use MinecraftStatusProtocol to get detailed status
    status = MinecraftStatusProtocol.query_server_status(host="localhost", port=self.server_port)

    if status:
        # Add performance data if available
        performance = self._get_performance_impl()
        if performance:
            status['performance'] = performance

        # Notify of status update
        if self.on_status_update:
            try:
                self.on_status_update(status)
            except Exception as e:
                log_exception(e, self.debug_mode)

        return status

    return None

def _get_performance_impl(self):
    """Implementation of performance data retrieval"""
    if not self.is_server_running():
        return None

    # Get performance data from performance monitor
    return self.performance_monitor.get_current_performance()

def _run_command_impl(self, command):
    """Implementation of running a server command"""
    if not self.is_server_running() or not self.rcon_enabled:
        return "Server is not running or RCON is not enabled"

    try:
        from mcrcon import MCRcon

        with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
            response = mcr.command(command)
            return response
    except Exception as e:
        log_exception(e, self.debug_mode)
        raise Exception(f"Failed to run command: {e}")

def _backup_world_impl(self):
    """Implementation of world backup"""
    try:
        # Get world name from server.properties
        world_name = "world"  # Default world name
        properties = self.properties_manager.load_properties()
        if properties and 'level-name' in properties:
            world_name = properties['level-name']

        # Check if world directory exists
        if not os.path.exists(world_name):
            # Create dummy directory for testing
            os.makedirs(world_name, exist_ok=True)
            with open(os.path.join(world_name, "level.dat"), "w") as f:
                f.write("Dummy level data for testing")

        # Create backup directory if it doesn't exist
        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"{world_name}_{timestamp}.zip")

        # If server is running, save the world first using RCON
        if self.is_server_running() and self.rcon_enabled:
            try:
                from mcrcon import MCRcon

                with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                    logging.info("Saving world...")
                    mcr.command("say Server backup starting, there may be lag...")
                    mcr.command("save-all")
                    time.sleep(5)  # Wait for save to complete
                    mcr.command("save-off")  # Disable saving during backup

                # Create zip backup
                logging.info(f"Creating backup of '{world_name}' to '{backup_file}'")
                with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(world_name):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(world_name)))

                # Re-enable saving
                if self.is_server_running() and self.rcon_enabled:
                    with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                        mcr.command("save-on")
                        mcr.command("say Server backup complete")

            except Exception as e:
                # Make sure save is re-enabled even if backup fails
                try:
                    if self.is_server_running() and self.rcon_enabled:
                        with MCRcon(self.rcon_host, self.rcon_password, port=self.rcon_port, timeout=self.rcon_timeout) as mcr:
                            mcr.command("save-on")
                            mcr.command("say Server backup failed")
                except:
                    pass
                raise e
        else:
            # Server is not running, simply zip the world
            logging.info(f"Creating backup of '{world_name}' to '{backup_file}'")
            with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(world_name):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(world_name)))

        logging.info(f"World backup completed: {backup_file}")
        return backup_file

    except Exception as e:
        log_exception(e, self.debug_mode)
        raise Exception(f"Backup failed: {e}")

def _load_properties_impl(self):
    """Implementation of loading server properties"""
    try:
        properties = self.properties_manager.load_properties()
        return properties
    except Exception as e:
        log_exception(e, self.debug_mode)
        raise Exception(f"Failed to load properties: {e}")

def _save_properties_impl(self, properties):
    """Implementation of saving server properties"""
    try:
        # If properties is a simplified dictionary, update the full properties
        if properties and all(not isinstance(v, dict) for v in properties.values()):
            self.properties_manager.update_from_simplified(properties)
            result = self.properties_manager.save_properties()
        else:
            # Otherwise, save the full properties dictionary
            result = self.properties_manager.save_properties(properties)

        return result
    except Exception as e:
        log_exception(e, self.debug_mode)
        raise Exception(f"Failed to save properties: {e}")

def _update_java_settings_impl(self, min_memory, max_memory, jvm_args):
    """Implementation of updating Java settings"""
    try:
        result = self.properties_manager.edit_java_arguments(
            start_script=self.start_command,
            min_memory=min_memory,
            max_memory=max_memory,
            jvm_args=jvm_args
        )
        return result
    except Exception as e:
        log_exception(e, self.debug_mode)
        raise Exception(f"Failed to update Java settings: {e}")

def _get_player_info_impl(self, player_name):
    """Implementation of getting player information"""
    if not player_name or not self.is_server_running() or not self.rcon_enabled:
        return None

    return MinecraftStatusProtocol.get_player_details(self, player_name)

# Don't forget to update this method to signal the performance monitor to clean up on exit
def stop_all_threads(self):
    """Signal all threads to stop"""
    logging.info("Stopping all background threads")

    # Set stop event to signal threads to stop
    self.stop_event.set()

    # Wait briefly for threads to notice the signal
    time.sleep(0.5)

    # Unblock socket operations with a self-connection
    self._unblock_listener_socket()

    # Clean up performance monitor
    if hasattr(self, 'performance_monitor'):
        self.performance_monitor.cleanup()