"""
Core server management functionality for Minecraft Server Manager
"""

import os
import sys
import time
import socket
import subprocess
import threading
import logging
import re
import queue
import traceback
from typing import Optional, Dict, Any, Union

# Internal imports
from .utils import ServerState, TaskType, Task, log_exception
from .minecraft_protocol import MinecraftProtocol

# Check for mcrcon
try:
    from mcrcon import MCRcon
    RCON_AVAILABLE = True
except ImportError:
    RCON_AVAILABLE = False
    logging.warning("MCRCON not available. Install with: pip install mcrcon")

class ServerManager:
    """Manages the Minecraft server process and operations"""

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