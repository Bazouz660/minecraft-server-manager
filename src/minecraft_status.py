"""
Enhanced Minecraft protocol handling for detailed server status
"""

import socket
import json
import struct
import time
import logging
import threading
from io import BytesIO

class MinecraftStatusProtocol:
    """Implements the Minecraft Server List Ping protocol for detailed status"""

    @staticmethod
    def read_varint(stream):
        """Read a VarInt from a stream"""
        result = 0
        position = 0

        while True:
            current = stream.read(1)
            if not current:  # Connection closed
                return None

            value = ord(current)
            result |= (value & 0x7F) << position

            if not (value & 0x80):  # No more bytes
                break

            position += 7
            if position >= 32:
                raise ValueError("VarInt is too big")

        return result

    @staticmethod
    def write_varint(value):
        """Write a VarInt to a byte array"""
        result = bytearray()

        while True:
            byte = value & 0x7F
            value >>= 7

            if value:
                byte |= 0x80

            result.append(byte)

            if not value:
                break

        return bytes(result)

    @staticmethod
    def read_string(stream):
        """Read a string from a stream"""
        length = MinecraftStatusProtocol.read_varint(stream)
        if length is None:
            return None

        return stream.read(length).decode('utf-8')

    @staticmethod
    def write_string(value):
        """Write a string with length prefix"""
        encoded = value.encode('utf-8')
        return MinecraftStatusProtocol.write_varint(len(encoded)) + encoded

    @staticmethod
    def get_detailed_status(host="localhost", port=25565, timeout=5.0):
        """
        Get detailed server status using the Server List Ping protocol

        Returns a dictionary with the server status or None on failure
        """
        try:
            # Connect to the server
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((host, port))

                # Handshake packet
                # packet ID + protocol version + hostname + port + next state (1 for status)
                handshake = (
                    b'\x00' +  # Packet ID (0x00 for handshake)
                    MinecraftStatusProtocol.write_varint(47) +  # Protocol version 1.8+ (47)
                    MinecraftStatusProtocol.write_string(host) +
                    struct.pack('>H', port) +  # unsigned short for port
                    b'\x01'  # Next state: 1 for status query
                )

                # Prepend packet length as VarInt
                handshake = MinecraftStatusProtocol.write_varint(len(handshake)) + handshake

                # Send handshake
                sock.sendall(handshake)

                # Status request packet (0x00, empty payload)
                sock.sendall(b'\x01\x00')

                # Read response
                # First read the length prefix
                raw_length = sock.recv(1)
                if not raw_length:
                    return None

                stream = BytesIO(raw_length + sock.recv(2048))
                packet_length = MinecraftStatusProtocol.read_varint(stream)

                # Read packet ID
                packet_id = MinecraftStatusProtocol.read_varint(stream)
                if packet_id != 0x00:  # Status response packet ID should be 0x00
                    return None

                # Read the JSON response string
                json_length = MinecraftStatusProtocol.read_varint(stream)
                json_data = stream.read(json_length).decode('utf-8')

                # Parse the JSON data
                status = json.loads(json_data)

                # Optional: Send ping packet to measure latency
                ping_time = int(time.time() * 1000)

                # Send ping packet (ID 0x01)
                ping = b'\x09\x01' + struct.pack('>Q', ping_time)  # 0x09 = packet length, 0x01 = packet ID, Q = long long
                sock.sendall(ping)

                # Read pong response
                try:
                    raw_length = sock.recv(1)
                    if not raw_length:
                        # No ping response, but we still have status
                        return status

                    stream = BytesIO(raw_length + sock.recv(16))
                    packet_length = MinecraftStatusProtocol.read_varint(stream)
                    packet_id = MinecraftStatusProtocol.read_varint(stream)

                    if packet_id == 0x01:  # Pong packet ID
                        pong_time = struct.unpack('>Q', stream.read(8))[0]
                        latency = int(time.time() * 1000) - pong_time
                        status['latency'] = latency
                except:
                    # If ping fails, continue with the status we have
                    pass

                return status

        except Exception as e:
            logging.debug(f"Error getting detailed server status: {e}")
            return None

    @staticmethod
    def query_server_status(host="localhost", port=25565):
        """
        Query server status and return a formatted dictionary

        Returns:
        - None if server is offline
        - Status dictionary with version, players, motd, etc. if online
        """
        # Get detailed status
        status = MinecraftStatusProtocol.get_detailed_status(host, port)

        if not status:
            return None

        # Extract and format information
        result = {
            'online': True,
            'latency': status.get('latency', 0)
        }

        # Version info
        if 'version' in status:
            result['version'] = status['version'].get('name', 'Unknown')
            result['protocol'] = status['version'].get('protocol', 0)

        # Player info
        if 'players' in status:
            players = status['players']
            result['players'] = {
                'online': players.get('online', 0),
                'max': players.get('max', 0)
            }

            # Player sample list
            if 'sample' in players:
                result['players']['sample'] = players['sample']

        # MOTD (description)
        if 'description' in status:
            desc = status['description']

            # Parse description - can be a string or a JSON object with text formatting
            if isinstance(desc, str):
                result['motd'] = desc
            elif isinstance(desc, dict):
                # Try to extract text from the JSON format
                if 'text' in desc:
                    result['motd'] = desc['text']
                else:
                    # More complex format with multiple components
                    motd = ""
                    if 'extra' in desc:
                        for part in desc['extra']:
                            if isinstance(part, str):
                                motd += part
                            elif isinstance(part, dict) and 'text' in part:
                                motd += part['text']
                    result['motd'] = motd

        # Favicon
        if 'favicon' in status:
            result['favicon'] = status['favicon']

        return result

    @staticmethod
    def get_performance_data(server_manager):
        """
        Get server performance data using RCON

        Returns a dictionary with ram, cpu, and tps information
        """
        if not server_manager.rcon_enabled or not server_manager.is_server_running():
            return None

        try:
            # Use server_manager's RCON connection to get performance data
            from mcrcon import MCRcon

            performance = {
                'ram': 0,
                'ram_max': 0,
                'cpu': 0,
                'tps': 20.0
            }

            with MCRcon(server_manager.rcon_host, server_manager.rcon_password,
                      port=server_manager.rcon_port, timeout=server_manager.rcon_timeout) as mcr:

                # Try to get TPS info (works on Paper and Spigot)
                try:
                    response = mcr.command("tps")

                    # Parse tps values - format varies by server type
                    parts = response.split()
                    for part in parts:
                        if part.replace('.', '').isdigit():
                            tps_value = float(part)
                            if tps_value <= 20:  # Valid TPS value
                                performance['tps'] = tps_value
                                break
                except:
                    # Default to 20 if we can't get TPS
                    performance['tps'] = 20.0

            # If RCON couldn't get detailed stats, use process stats as fallback
            if performance['ram'] == 0:
                try:
                    import psutil
                    for proc in psutil.process_iter(['name', 'memory_info']):
                        if proc.info['name'] and 'java' in proc.info['name'].lower():
                            # This is likely the Java process running our server
                            ram_usage = proc.info['memory_info'].rss / (1024 * 1024)  # MB
                            performance['ram'] = int(ram_usage)
                            performance['ram_max'] = int(ram_usage * 1.5)  # Estimate
                            performance['cpu'] = proc.cpu_percent(interval=0.1)
                            break
                except:
                    # Fallback to default values if psutil fails
                    performance['ram'] = 1024
                    performance['ram_max'] = 4096
                    performance['cpu'] = 10

            return performance

        except Exception as e:
            logging.debug(f"Error getting performance data: {e}")
            return {
                'ram': 1024,
                'ram_max': 4096,
                'cpu': 10,
                'tps': 20.0
            }  # Return default values on error

    @staticmethod
    def get_player_details(server_manager, player_name):
        """
        Get detailed information about a player using RCON

        Returns a dictionary with player information or None on failure
        """
        if not server_manager.rcon_enabled or not server_manager.is_server_running():
            return None

        try:
            from mcrcon import MCRcon

            with MCRcon(server_manager.rcon_host, server_manager.rcon_password,
                      port=server_manager.rcon_port, timeout=server_manager.rcon_timeout) as mcr:

                # Basic player info - will work on vanilla servers
                player_info = {
                    'Name': player_name,
                    'Status': 'Online'
                }

                # Try to get player's gamemode
                try:
                    response = mcr.command(f"data get entity {player_name} playerGameType")
                    if "playerGameType: " in response:
                        gamemode_id = int(response.split("playerGameType: ")[1].strip())
                        gamemodes = {0: "Survival", 1: "Creative", 2: "Adventure", 3: "Spectator"}
                        player_info['GameMode'] = gamemodes.get(gamemode_id, "Unknown")
                except:
                    player_info['GameMode'] = "Unknown"

                # Return what we have
                return player_info

        except Exception as e:
            logging.debug(f"Error getting player details: {e}")
            return None