"""
Minecraft protocol handling for server status checks and connection detection
"""

import socket
import logging
import struct

class MinecraftProtocol:
    """Handles Minecraft protocol interactions"""

    @staticmethod
    def read_varint(sock):
        """Read a VarInt from the socket"""
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

    @staticmethod
    def write_varint(value):
        """Write a value as a VarInt"""
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
    def read_string(sock):
        """Read a string (prefixed with its length as a VarInt) from the socket"""
        length = MinecraftProtocol.read_varint(sock)
        if length is None:
            return None

        try:
            string_bytes = sock.recv(length)
            if len(string_bytes) < length:  # Connection closed
                return None

            return string_bytes.decode('utf-8')
        except:
            return None

    @staticmethod
    def write_string(value):
        """Write a string prefixed with its length as a VarInt"""
        value_bytes = value.encode('utf-8')
        return MinecraftProtocol.write_varint(len(value_bytes)) + value_bytes

    @staticmethod
    def parse_handshake(sock):
        """Parse a handshake packet from the socket"""
        try:
            # Read protocol version
            protocol_version = MinecraftProtocol.read_varint(sock)
            if protocol_version is None:
                return None

            # Read server address
            server_address = MinecraftProtocol.read_string(sock)
            if server_address is None:
                return None

            # Read server port
            try:
                port_data = sock.recv(2)
                if len(port_data) < 2:
                    return None
                port = struct.unpack('>H', port_data)[0]
            except:
                return None

            # Read next state
            next_state = MinecraftProtocol.read_varint(sock)
            if next_state is None:
                return None

            return {
                'protocol_version': protocol_version,
                'server_address': server_address,
                'port': port,
                'next_state': next_state
            }
        except Exception as e:
            logging.debug(f"Error parsing handshake: {e}")
            return None

    @staticmethod
    def parse_login_start(sock):
        """Parse a login start packet from the socket"""
        try:
            # Read username
            username = MinecraftProtocol.read_string(sock)
            return {'username': username} if username else None
        except Exception as e:
            logging.debug(f"Error parsing login start: {e}")
            return None

    @staticmethod
    def handle_client_connection(sock, addr):
        """
        Handle a Minecraft client connection and determine the request type

        Returns:
            "login" - Player is attempting to join the server
            "status" - Client is requesting server status (ping)
            None - Invalid or incomplete request
        """
        try:
            sock.settimeout(2.0)  # Set a timeout to avoid hanging

            # Read packet length
            packet_length = MinecraftProtocol.read_varint(sock)
            if packet_length is None:
                return None

            # Read packet ID
            packet_id = MinecraftProtocol.read_varint(sock)
            if packet_id is None:
                return None

            # Handshake packet (should be ID 0)
            if packet_id != 0:
                logging.debug(f"Unexpected packet ID: {packet_id}")
                return None

            # Parse handshake
            handshake = MinecraftProtocol.parse_handshake(sock)
            if not handshake:
                return None

            next_state = handshake.get('next_state')
            logging.debug(f"Received handshake with next_state={next_state} from {addr}")

            # State 1 = Status Request (ping/pong)
            # State 2 = Login Request (actual join)
            if next_state == 1:
                # Try to read the next packet (status request)
                packet_length = MinecraftProtocol.read_varint(sock)
                packet_id = MinecraftProtocol.read_varint(sock)

                # Status request packet (should be ID 0)
                if packet_id == 0:
                    return "status"
            elif next_state == 2:
                # Try to read the next packet (login start)
                packet_length = MinecraftProtocol.read_varint(sock)
                if packet_length is None:
                    return None

                packet_id = MinecraftProtocol.read_varint(sock)
                if packet_id is None:
                    return None

                # Login start packet (should be ID 0)
                if packet_id == 0:
                    login_info = MinecraftProtocol.parse_login_start(sock)
                    if login_info and login_info.get('username'):
                        logging.info(f"Login attempt by {login_info['username']} from {addr}")
                        return "login"

            return None
        except Exception as e:
            logging.debug(f"Error handling connection: {e}")
            return None

    @staticmethod
    def ping_minecraft_server(host="localhost", port=25565):
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
                    s.connect((host, port))
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
                    port_bytes = port.to_bytes(2, byteorder='big')
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