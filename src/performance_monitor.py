"""
Performance monitoring for Minecraft Server Manager
"""

import os
import time
import logging
import json
import threading
from datetime import datetime, timedelta

class PerformanceMonitor:
    """Monitors Minecraft server performance metrics"""

    def __init__(self, server_manager):
        self.server_manager = server_manager
        self.debug_mode = server_manager.debug_mode

        # Performance data storage
        self.performance_history = {
            'ram': [],      # Memory usage in MB
            'cpu': [],      # CPU usage in percent
            'tps': [],      # Ticks per second
            'players': [],  # Player count
            'timestamps': [] # Timestamp for each data point
        }

        # Maximum history length (default: 24 hours with 5-minute intervals = 288 data points)
        self.max_history_length = 288

        # Sample data for testing/development
        self._initialize_sample_data()

        # Performance data file
        self.data_file = "performance_history.json"

        # Lock for thread safety
        self.lock = threading.RLock()

        # Load existing performance history if available
        self.load_history()

    def _initialize_sample_data(self):
        """Initialize with sample data if no real data exists yet"""
        # This ensures we have something to display in the UI
        if not self.performance_history['timestamps']:
            current_time = time.time()

            # Add 10 sample data points at 5-minute intervals
            for i in range(10):
                timestamp = current_time - (9 - i) * 300  # 5-minute intervals
                self.performance_history['timestamps'].append(timestamp)
                self.performance_history['ram'].append(1024 + i * 50)  # Simulated RAM usage
                self.performance_history['cpu'].append(10 + i * 2)     # Simulated CPU usage
                self.performance_history['tps'].append(20 - (i % 5))   # Simulated TPS
                self.performance_history['players'].append(i % 4)      # Simulated player count

    def load_history(self):
        """Load performance history from file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)

                    with self.lock:
                        # Validate and load data
                        if all(key in data for key in ['ram', 'cpu', 'tps', 'players', 'timestamps']):
                            self.performance_history = data

                            # Convert timestamps from string back to float if needed
                            if self.performance_history['timestamps'] and isinstance(self.performance_history['timestamps'][0], str):
                                self.performance_history['timestamps'] = [float(ts) for ts in self.performance_history['timestamps']]

                            logging.info(f"Loaded {len(self.performance_history['timestamps'])} performance history data points")
                        else:
                            logging.warning("Performance history file has invalid format")
        except Exception as e:
            logging.error(f"Error loading performance history: {e}")
            # Fallback to sample data
            self._initialize_sample_data()

    def save_history(self):
        """Save performance history to file"""
        try:
            with self.lock:
                with open(self.data_file, 'w') as f:
                    json.dump(self.performance_history, f)

            logging.debug("Saved performance history")
        except Exception as e:
            logging.error(f"Error saving performance history: {e}")

    def add_data_point(self, ram=None, cpu=None, tps=None, players=None):
        """Add a new performance data point"""
        with self.lock:
            # If values are None, use the last value or default
            if ram is None and self.performance_history['ram']:
                ram = self.performance_history['ram'][-1]
            elif ram is None:
                ram = 0

            if cpu is None and self.performance_history['cpu']:
                cpu = self.performance_history['cpu'][-1]
            elif cpu is None:
                cpu = 0

            if tps is None and self.performance_history['tps']:
                tps = self.performance_history['tps'][-1]
            elif tps is None:
                tps = 0

            if players is None and self.performance_history['players']:
                players = self.performance_history['players'][-1]
            elif players is None:
                players = 0

            # Add data point
            self.performance_history['ram'].append(ram)
            self.performance_history['cpu'].append(cpu)
            self.performance_history['tps'].append(tps)
            self.performance_history['players'].append(players)
            self.performance_history['timestamps'].append(time.time())

            # Trim to max length
            if len(self.performance_history['timestamps']) > self.max_history_length:
                self.performance_history['ram'] = self.performance_history['ram'][-self.max_history_length:]
                self.performance_history['cpu'] = self.performance_history['cpu'][-self.max_history_length:]
                self.performance_history['tps'] = self.performance_history['tps'][-self.max_history_length:]
                self.performance_history['players'] = self.performance_history['players'][-self.max_history_length:]
                self.performance_history['timestamps'] = self.performance_history['timestamps'][-self.max_history_length:]

            # Save to file periodically (every 5 data points)
            if len(self.performance_history['timestamps']) % 5 == 0:
                self.save_history()

    def get_current_performance(self):
        """Get current performance data from the server"""
        from .minecraft_status import MinecraftStatusProtocol

        if not self.server_manager.is_server_running():
            return {
                'ram': 0,
                'ram_max': 0,
                'cpu': 0,
                'tps': 0,
                'players': 0,
                'timestamp': time.time()
            }

        # Get performance data from the MinecraftStatusProtocol
        performance = MinecraftStatusProtocol.get_performance_data(self.server_manager)

        if performance:
            # Add player count
            performance['players'] = self.server_manager.player_count

            # Add timestamp
            performance['timestamp'] = time.time()

            # Add to history
            self.add_data_point(
                ram=performance.get('ram', None),
                cpu=performance.get('cpu', None),
                tps=performance.get('tps', None),
                players=performance.get('players', None)
            )

            return performance

        # If we couldn't get performance data, return the latest from history
        if self.performance_history['timestamps']:
            idx = -1
            return {
                'ram': self.performance_history['ram'][idx],
                'ram_max': 4096,  # Default estimate
                'cpu': self.performance_history['cpu'][idx],
                'tps': self.performance_history['tps'][idx],
                'players': self.performance_history['players'][idx],
                'timestamp': self.performance_history['timestamps'][idx]
            }

        # Fallback to default values if no history exists
        return {
            'ram': 1024,
            'ram_max': 4096,
            'cpu': 10,
            'tps': 20,
            'players': 0,
            'timestamp': time.time()
        }

    def get_history(self, timeframe_hours=1):
        """
        Get performance history for the specified timeframe

        Args:
            timeframe_hours: Number of hours to retrieve (default: 1)

        Returns:
            Dictionary with performance history
        """
        with self.lock:
            if not self.performance_history['timestamps']:
                return None

            # Calculate cutoff time
            cutoff_time = time.time() - (timeframe_hours * 3600)

            # Find the index of the first timestamp after cutoff
            start_index = 0
            for i, ts in enumerate(self.performance_history['timestamps']):
                if ts >= cutoff_time:
                    start_index = i
                    break

            # Extract the data for the timeframe
            result = {
                'ram': self.performance_history['ram'][start_index:],
                'cpu': self.performance_history['cpu'][start_index:],
                'tps': self.performance_history['tps'][start_index:],
                'players': self.performance_history['players'][start_index:],
                'timestamps': self.performance_history['timestamps'][start_index:],
                'formatted_times': []
            }

            # Add formatted timestamps for display
            for ts in result['timestamps']:
                dt = datetime.fromtimestamp(ts)
                result['formatted_times'].append(dt.strftime('%H:%M'))

            return result

    def get_process_stats(self):
        """Get CPU and memory usage of the Minecraft server process"""
        if not self.server_manager.is_server_running():
            return None

        try:
            import psutil

            # Find Java process by checking for Minecraft server in command line
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
                if proc.info['name'] and 'java' in proc.info['name'].lower():
                    # Check if this is likely our Minecraft server
                    cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                    if 'minecraft' in cmdline or 'spigot' in cmdline or 'paper' in cmdline or 'bukkit' in cmdline:
                        # Get process stats
                        with proc.oneshot():
                            # Update CPU percent (requires a second call to get accurate value)
                            proc.cpu_percent()
                            time.sleep(0.1)
                            cpu_percent = proc.cpu_percent()

                            # Get memory info
                            memory_mb = proc.memory_info().rss / (1024 * 1024)

                            return {
                                'pid': proc.pid,
                                'cpu': cpu_percent,
                                'ram': int(memory_mb),
                                'ram_max': int(memory_mb * 1.5)  # Estimate max memory
                            }

            # If no matching process found, return simulated data
            return {
                'pid': 0,
                'cpu': 10,
                'ram': 1024,
                'ram_max': 4096
            }

        except Exception as e:
            logging.debug(f"Error getting process stats: {e}")

            # Return simulated data on error
            return {
                'pid': 0,
                'cpu': 10,
                'ram': 1024,
                'ram_max': 4096
            }

    def cleanup(self):
        """Clean up resources when shutting down"""
        self.save_history()