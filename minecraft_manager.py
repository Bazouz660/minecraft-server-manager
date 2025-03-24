import os
import sys
import time
import socket
import subprocess
import threading
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import configparser
import re
import json
import queue
import signal
import traceback
from typing import Optional, Dict, List, Tuple, Any, Union

# Version number
VERSION = "1.0.0"

# Check for mcrcon
try:
    from mcrcon import MCRcon
    RCON_AVAILABLE = True
except ImportError:
    RCON_AVAILABLE = False
    print("MCRCON not available. Install with: pip install mcrcon")

# Basic configuration
CONFIG_FILE = "server_config.ini"
DEFAULT_CONFIG = """
[Server]
port = 25565
start_command = start.bat
inactivity_timeout = 600
check_interval = 60
startup_wait = 5
shutdown_timeout = 30

[RCON]
enabled = true
host = localhost
port = 25575
password = changeme
timeout = 3

[GUI]
auto_scroll_logs = true
theme = default
update_interval = 1000
max_log_lines = 1000

[System]
debug_mode = false
"""

class ServerState:
    """Server state constants"""
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"

class TaskType:
    """Task types for the worker queue"""
    START_SERVER = "start_server"
    STOP_SERVER = "stop_server"
    RESTART_SERVER = "restart_server"
    CHECK_STATUS = "check_status"
    GET_PLAYERS = "get_players"

class Task:
    """Task object for the worker queue"""
    def __init__(self, task_type, callback=None, **kwargs):
        self.type = task_type
        self.callback = callback
        self.args = kwargs
        self.result = None
        self.error = None
        self.completed = False

class MinecraftServerManager:
    """Manager for Minecraft server operations"""

    def __init__(self, config_file=CONFIG_FILE):
        # Set up logging
        self.setup_logging()

        # Load configuration
        self.config = self.load_config(config_file)

        # Server info
        self.server_port = self.config.getint('Server', 'port')
        self.start_command = self.config.get('Server', 'start_command')
        self.inactivity_timeout = self.config.getint('Server', 'inactivity_timeout')
        self.check_interval = self.config.getint('Server', 'check_interval')
        self.startup_wait = self.config.getint('Server', 'startup_wait')
        self.shutdown_timeout = self.config.getint('Server', 'shutdown_timeout')

        # RCON settings
        self.rcon_enabled = RCON_AVAILABLE and self.config.getboolean('RCON', 'enabled')
        if self.rcon_enabled:
            self.rcon_host = self.config.get('RCON', 'host')
            self.rcon_port = self.config.getint('RCON', 'port')
            self.rcon_password = self.config.get('RCON', 'password')
            self.rcon_timeout = self.config.getint('RCON', 'timeout')

        # Debug mode
        self.debug_mode = self.config.getboolean('System', 'debug_mode')

        # State variables and synchronization
        self.state_lock = threading.RLock()
        self.state = ServerState.OFFLINE
        self.process = None
        self.start_time = 0
        self.player_count = 0

        # Thread control
        self.stop_event = threading.Event()
        self.port_listener_thread = None
        self.monitor_thread = None
        self.worker_thread = None
        self.task_queue = queue.Queue()

        # Event callback
        self.on_state_change = None
        self.on_player_count_change = None
        self.on_log_message = None

        # Start worker thread
        self.worker_thread = threading.Thread(target=self._worker_thread_func, daemon=True)
        self.worker_thread.start()

    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler("server_manager.log"),
                logging.StreamHandler()
            ]
        )

    def load_config(self, config_file):
        """Load or create configuration file"""
        config = configparser.ConfigParser()

        # Create default config if file doesn't exist
        if not os.path.exists(config_file):
            with open(config_file, 'w') as f:
                f.write(DEFAULT_CONFIG)
            logging.info(f"Created default configuration file: {config_file}")

        config.read(config_file)
        return config

    def save_config(self, config_file=CONFIG_FILE):
        """Save configuration to file"""
        try:
            with open(config_file, 'w') as f:
                self.config.write(f)
            logging.info(f"Configuration saved to {config_file}")
            return True
        except Exception as e:
            logging.error(f"Failed to save configuration: {e}")
            return False

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
            logging.info(f"Server state changed: {old_state} -> {new_state}")
            if self.on_state_change:
                try:
                    self.on_state_change(old_state, new_state)
                except Exception as e:
                    logging.error(f"Error in state change callback: {e}")

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

    def check_bat_file(self):
        """Check if the start.bat file exists and has a pause command"""
        if not self.start_command.endswith('.bat'):
            return

        if not os.path.exists(self.start_command):
            logging.warning(f"Start command '{self.start_command}' not found")
            return

        # Read the current content
        with open(self.start_command, 'r') as f:
            content = f.read()

        # Add pause if needed
        if "pause" not in content.lower():
            logging.info(f"Adding 'pause' command to {self.start_command}")
            with open(self.start_command, 'a') as f:
                f.write("\n\necho. \necho Server stopped. Press any key to close window.\npause > nul")

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
                    else:
                        logging.warning(f"Unknown task type: {task.type}")
                except Exception as e:
                    logging.error(f"Error processing task {task.type}: {e}")
                    if self.debug_mode:
                        logging.error(traceback.format_exc())
                    task.error = str(e)

                # Mark task as completed
                task.completed = True

                # Execute callback if provided
                if task.callback:
                    try:
                        task.callback(task)
                    except Exception as e:
                        logging.error(f"Error in task callback: {e}")

                # Mark task as done in the queue
                self.task_queue.task_done()

            except Exception as e:
                logging.error(f"Error in worker thread: {e}")
                if self.debug_mode:
                    logging.error(traceback.format_exc())

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
            logging.error(f"Error starting server: {e}")
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
                logging.error(f"RCON stop failed: {e}")

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
                            logging.error(f"Failed to terminate process tree: {e}")
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
                                logging.error(f"Failed to kill server process: {e}")
                except Exception as e:
                    logging.error(f"Failed to terminate server process: {e}")

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
                                logging.error(f"Error in player count callback: {e}")

                    return count
        except ConnectionRefusedError:
            # This is normal during startup
            logging.debug("RCON connection refused")
        except Exception as e:
            logging.error(f"RCON error getting player count: {e}")

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
                ping_result = self._ping_minecraft_server()

                if ping_result == "online":
                    # Server is responding to ping requests
                    if current_state == ServerState.STARTING:
                        logging.info("Server is now fully started and responding to ping requests")
                        self.set_state(ServerState.RUNNING)
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

    def _ping_minecraft_server(self):
        """
        Ping the Minecraft server to check its status
        Returns:
        - "online": Server is fully started and responding to ping
        - "starting": Server port is open but not responding to ping properly
        - "offline": Server is not responding
        """
        try:
            # First check if the port is open
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                try:
                    s.connect(("localhost", self.server_port))
                except:
                    return "offline"

                # If we can connect, the port is open, but it might not be fully started
                # Try to send a Server List Ping (SLP) packet - simplest version
                try:
                    # Handshake packet
                    packet = bytearray([
                        0x00,  # Packet ID
                        0x00,  # Protocol version (VarInt)
                        0x09,  # String length (VarInt)
                    ])
                    packet.extend(b'localhost')  # Server address

                    # Add port (unsigned short)
                    port_bytes = self.server_port.to_bytes(2, byteorder='big')
                    packet.extend(port_bytes)

                    # Add next state (1 = Status)
                    packet.append(0x01)

                    # Add packet length as VarInt at the beginning
                    length = len(packet)
                    length_bytes = bytearray()
                    while True:
                        byte = length & 0x7F
                        length >>= 7
                        if length:
                            byte |= 0x80
                        length_bytes.append(byte)
                        if not length:
                            break

                    # Construct final packet with length
                    final_packet = length_bytes + packet

                    # Send handshake
                    s.sendall(final_packet)

                    # Send status request (empty packet with ID 0)
                    s.sendall(bytearray([0x01, 0x00]))

                    # Read response length
                    response = s.recv(1)
                    if not response:
                        return "starting"  # Port is open but server not ready

                    # If we received a response, parse it to verify it's a Minecraft server
                    if len(response) > 0:
                        return "online"

                except Exception as e:
                    logging.debug(f"Error during SLP check: {e}")
                    return "starting"  # Port is open but server not fully initialized
        except Exception as e:
            logging.debug(f"Error checking server status: {e}")

        return "offline"

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
                        logging.error(f"Error in port listener: {e}")
                        if self.debug_mode:
                            logging.error(traceback.format_exc())
                    time.sleep(1)
        except Exception as e:
            if not self.stop_event.is_set():
                logging.error(f"Error in port listener thread: {e}")
                if self.debug_mode:
                    logging.error(traceback.format_exc())
        finally:
            if socket_bound and server_socket:
                try:
                    server_socket.close()
                    logging.info("Server socket closed")
                except Exception as e:
                    logging.error(f"Error closing server socket: {e}")

            logging.info("Port listener thread exiting")

    def _handle_client_connection(self, client_socket, addr, server_socket):
        """Handle an incoming client connection"""
        try:
            # Determine if this is a login attempt or just a ping
            is_login_attempt = self._parse_minecraft_packet(client_socket)

            # Close client socket
            try:
                client_socket.close()
            except:
                pass

            if is_login_attempt:
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
            logging.error(f"Error handling client connection: {e}")
            if self.debug_mode:
                logging.error(traceback.format_exc())

    def _parse_minecraft_packet(self, client_socket):
        """
        Parse incoming Minecraft packet to determine if it's a login attempt
        Returns True for login attempt, False for ping/status request
        """
        try:
            # Set a short timeout for reads
            client_socket.settimeout(2)

            # First read the packet length as a VarInt
            packet_length = self._read_varint(client_socket)
            if packet_length is None:
                return False

            # Read packet ID (should be 0x00 for handshake)
            packet_id = self._read_varint(client_socket)
            if packet_id != 0:  # Not a handshake
                return False

            # Read protocol version (VarInt)
            protocol_version = self._read_varint(client_socket)
            if protocol_version is None:
                return False

            # Read server address (String prefixed with length)
            # First read string length
            string_length = self._read_varint(client_socket)
            if string_length is None:
                return False

            # Then read the string data
            if string_length > 0:
                try:
                    server_address = client_socket.recv(string_length)
                    if len(server_address) < string_length:
                        return False
                except:
                    return False

            # Read server port (Unsigned Short - 2 bytes)
            try:
                port_data = client_socket.recv(2)
                if len(port_data) < 2:
                    return False
            except:
                return False

            # Read next state (VarInt: 1 = Status, 2 = Login)
            next_state = self._read_varint(client_socket)
            if next_state is None:
                return False

            # Return True if next_state is 2 (Login)
            return next_state == 2
        except Exception as e:
            logging.debug(f"Error parsing Minecraft packet: {e}")
            return False

    def _read_varint(self, sock):
        """Read a VarInt from a socket"""
        value = 0
        position = 0

        while True:
            try:
                current_byte = sock.recv(1)
                if not current_byte:  # Connection closed
                    return None

                # Convert byte to int
                current = current_byte[0]

                value |= (current & 0x7F) << position

                if not (current & 0x80):  # No more bytes
                    break

                position += 7
                if position >= 32:
                    # VarInt is too big
                    return None
            except:
                return None

        return value

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
        self.root.title(f"Minecraft Server Manager v{VERSION}")
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
        self.log_handler = self.TextHandler(self.log_queue)
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
            self.status_var.set(server_state)

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
            logging.error(f"Error updating status: {e}")
            if self.server_manager.debug_mode:
                logging.error(traceback.format_exc())

        # Schedule next update
        self.status_update_id = self.root.after(self.update_interval, self.update_status)

    def on_status_check_result(self, task):
        """Callback for server status check task"""
        # We don't need to do anything here as the server manager
        # will update its state and call our state change callback
        pass

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
                self.server_manager.save_config()

                # Close dialog
                settings_window.destroy()

                # Show confirmation
                messagebox.showinfo("Settings", "Settings saved successfully")

                # Note: Server needs to be restarted for some settings to take effect
                if self.server_manager.is_server_running():
                    messagebox.showinfo("Settings", "Some settings will take effect after server restart")

            except Exception as e:
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

    class TextHandler(logging.Handler):
        """Custom logging handler that queues logs for the GUI"""
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

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def main():
    """Main entry point"""
    try:
        # Create server manager
        server_manager = MinecraftServerManager()

        # Check and modify start.bat if needed
        server_manager.check_bat_file()

        # Create and run GUI
        gui = ServerManagerGUI(server_manager)
        gui.run()
    except Exception as e:
        logging.critical(f"Fatal error: {e}", exc_info=True)
        messagebox.showerror("Fatal Error", f"A critical error occurred: {e}")
        if hasattr(os, '_exit'):
            os._exit(1)


if __name__ == "__main__":
    main()