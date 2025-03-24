"""
Server properties management for Minecraft Server Manager
"""

import os
import logging
import re
import shutil
from datetime import datetime

class ServerPropertiesManager:
    """Manages Minecraft server.properties file"""

    def __init__(self, server_dir="."):
        self.server_dir = server_dir
        self.properties_file = os.path.join(server_dir, "server.properties")

        # Default properties with descriptions
        self.default_properties = {
            "gamemode": {
                "value": "survival",
                "description": "Game mode (survival, creative, adventure, spectator)",
                "options": ["survival", "creative", "adventure", "spectator"]
            },
            "difficulty": {
                "value": "easy",
                "description": "Game difficulty",
                "options": ["peaceful", "easy", "normal", "hard"]
            },
            "level-name": {
                "value": "world",
                "description": "World name/folder"
            },
            "motd": {
                "value": "A Minecraft Server",
                "description": "Message of the Day"
            },
            "pvp": {
                "value": "true",
                "description": "Allow players to fight each other",
                "options": ["true", "false"]
            },
            "generate-structures": {
                "value": "true",
                "description": "Generate villages, etc.",
                "options": ["true", "false"]
            },
            "max-players": {
                "value": "20",
                "description": "Maximum number of players allowed"
            },
            "server-port": {
                "value": "25565",
                "description": "Port the server listens on"
            },
            "allow-nether": {
                "value": "true",
                "description": "Allow Nether dimension",
                "options": ["true", "false"]
            },
            "enable-command-block": {
                "value": "false",
                "description": "Enable command blocks",
                "options": ["true", "false"]
            },
            "allow-flight": {
                "value": "false",
                "description": "Allow players to fly in survival mode",
                "options": ["true", "false"]
            },
            "online-mode": {
                "value": "true",
                "description": "Check connecting players against Minecraft account database",
                "options": ["true", "false"]
            },
            "view-distance": {
                "value": "10",
                "description": "Distance in chunks that players can see"
            },
            "spawn-protection": {
                "value": "16",
                "description": "Radius of spawn area protection from building"
            },
            "op-permission-level": {
                "value": "4",
                "description": "Permission level for ops",
                "options": ["1", "2", "3", "4"]
            },
            "enable-rcon": {
                "value": "true",
                "description": "Enable remote console protocol",
                "options": ["true", "false"]
            },
            "rcon.port": {
                "value": "25575",
                "description": "RCON port"
            },
            "rcon.password": {
                "value": "changeme",
                "description": "RCON password"
            }
        }

        # Properties loaded from file
        self.properties = {}

    def load_properties(self):
        """Load server properties from the properties file"""
        self.properties = {}

        try:
            if not os.path.exists(self.properties_file):
                logging.warning(f"Server properties file not found: {self.properties_file}")
                # Use default properties as fallback
                for key, prop in self.default_properties.items():
                    if isinstance(prop, dict):
                        self.properties[key] = prop["value"]
                    else:
                        self.properties[key] = prop
                return self.properties

            with open(self.properties_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key_value = line.split('=', 1)
                        if len(key_value) == 2:
                            key, value = key_value
                            self.properties[key.strip()] = value.strip()

            # Add any missing default properties
            for key, prop in self.default_properties.items():
                if key not in self.properties:
                    if isinstance(prop, dict):
                        self.properties[key] = prop["value"]
                    else:
                        self.properties[key] = prop

            logging.info(f"Loaded {len(self.properties)} server properties")
            return self.properties

        except Exception as e:
            logging.error(f"Error loading server properties: {e}")

            # Use default properties as fallback on error
            for key, prop in self.default_properties.items():
                if isinstance(prop, dict):
                    self.properties[key] = prop["value"]
                else:
                    self.properties[key] = prop

            return self.properties

    def save_properties(self, properties=None):
        """Save server properties to the properties file"""
        if properties:
            self.properties = properties

        try:
            # Create backup of existing file
            if os.path.exists(self.properties_file):
                backup_file = f"{self.properties_file}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                shutil.copy2(self.properties_file, backup_file)
                logging.info(f"Created backup of server.properties: {backup_file}")

            with open(self.properties_file, 'w') as f:
                f.write("# Minecraft server properties\n")
                f.write(f"# Generated by Minecraft Server Manager on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                # Write each property
                for key, value in sorted(self.properties.items()):
                    f.write(f"{key}={value}\n")

            logging.info(f"Saved {len(self.properties)} server properties")
            return True

        except Exception as e:
            logging.error(f"Error saving server properties: {e}")
            return False

    def get_property_descriptions(self):
        """Get descriptions for properties"""
        descriptions = {}

        for key, prop in self.default_properties.items():
            if isinstance(prop, dict):
                descriptions[key] = {
                    "description": prop.get("description", ""),
                    "options": prop.get("options", [])
                }

        return descriptions

    def get_simplified_properties(self):
        """Get properties as a simple key-value dictionary"""
        return self.properties.copy()

    def update_from_simplified(self, simple_properties):
        """Update properties from a simple key-value dictionary"""
        for key, value in simple_properties.items():
            self.properties[key] = value

        return self.properties

    def edit_java_arguments(self, start_script="start.bat", min_memory=1024, max_memory=4096, jvm_args=None):
        """
        Edit Java arguments in the start script

        Args:
            start_script: Path to the start script
            min_memory: Minimum memory in MB
            max_memory: Maximum memory in MB
            jvm_args: Custom JVM arguments

        Returns:
            True if successful, False otherwise
        """
        try:
            script_path = os.path.join(self.server_dir, start_script)

            # For testing, we'll create a dummy script if it doesn't exist
            if not os.path.exists(script_path):
                logging.warning(f"Start script not found: {script_path}. Creating a sample script.")

                # Create a basic start script
                with open(script_path, 'w') as f:
                    if script_path.endswith('.bat'):
                        f.write("@echo off\n")
                        f.write("java -Xms1024M -Xmx2048M -jar server.jar nogui\n")
                        f.write("pause\n")
                    else:
                        f.write("#!/bin/bash\n")
                        f.write("java -Xms1024M -Xmx2048M -jar server.jar nogui\n")

            # Read current script
            with open(script_path, 'r') as f:
                content = f.read()

            # Create backup
            backup_script = f"{script_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            with open(backup_script, 'w') as f:
                f.write(content)

            # Windows batch script (.bat)
            if script_path.endswith('.bat'):
                # Find the Java command
                java_cmd_match = re.search(r'(java.exe|javaw.exe|java)\s+(.*)\s+-jar\s+(\S+)', content)

                if java_cmd_match:
                    java_exe = java_cmd_match.group(1)
                    args = java_cmd_match.group(2)
                    jar_file = java_cmd_match.group(3)

                    # Build new Java command with updated memory settings
                    new_cmd = f'{java_exe} -Xms{min_memory}M -Xmx{max_memory}M'

                    # Add custom JVM args if provided
                    if jvm_args:
                        new_cmd += f' {jvm_args}'

                    # Add jar file
                    new_cmd += f' -jar {jar_file}'

                    # Replace the Java command in the script
                    new_content = re.sub(r'(java.exe|javaw.exe|java)\s+(.*)\s+-jar\s+(\S+)', new_cmd, content)

                    # Write updated script
                    with open(script_path, 'w') as f:
                        f.write(new_content)

                    logging.info(f"Updated Java arguments in {script_path}")
                    return True
                else:
                    # Create a new script if no Java command found
                    server_jar = "server.jar"  # Default jar name

                    # Create a new batch script
                    new_content = f"@echo off\necho Starting Minecraft server with {max_memory}MB RAM\n"
                    new_content += f"java -Xms{min_memory}M -Xmx{max_memory}M"

                    # Add custom JVM args if provided
                    if jvm_args:
                        new_content += f' {jvm_args}'

                    new_content += f' -jar {server_jar} nogui\n'
                    new_content += "echo Server stopped. Press any key to close window.\npause > nul\n"

                    # Write new script
                    with open(script_path, 'w') as f:
                        f.write(new_content)

                    logging.info(f"Created new start script with Java arguments: {script_path}")
                    return True

            # Linux/macOS shell script (.sh)
            elif script_path.endswith('.sh'):
                # Find the Java command
                java_cmd_match = re.search(r'(java)\s+(.*)\s+-jar\s+(\S+)', content)

                if java_cmd_match:
                    java_exe = java_cmd_match.group(1)
                    args = java_cmd_match.group(2)
                    jar_file = java_cmd_match.group(3)

                    # Build new Java command with updated memory settings
                    new_cmd = f'{java_exe} -Xms{min_memory}M -Xmx{max_memory}M'

                    # Add custom JVM args if provided
                    if jvm_args:
                        new_cmd += f' {jvm_args}'

                    # Add jar file
                    new_cmd += f' -jar {jar_file}'

                    # Replace the Java command in the script
                    new_content = re.sub(r'(java)\s+(.*)\s+-jar\s+(\S+)', new_cmd, content)

                    # Write updated script
                    with open(script_path, 'w') as f:
                        f.write(new_content)

                    # Make sure the script is executable
                    os.chmod(script_path, 0o755)

                    logging.info(f"Updated Java arguments in {script_path}")
                    return True
                else:
                    # Create a new script if no Java command found
                    server_jar = "server.jar"  # Default jar name

                    # Create a new shell script
                    new_content = "#!/bin/bash\necho \"Starting Minecraft server with {max_memory}MB RAM\"\n"
                    new_content += f"java -Xms{min_memory}M -Xmx{max_memory}M"

                    # Add custom JVM args if provided
                    if jvm_args:
                        new_content += f' {jvm_args}'

                    new_content += f' -jar {server_jar} nogui\n'
                    new_content += "echo \"Server stopped.\"\n"

                    # Write new script
                    with open(script_path, 'w') as f:
                        f.write(new_content)

                    # Make it executable
                    os.chmod(script_path, 0o755)

                    logging.info(f"Created new start script with Java arguments: {script_path}")
                    return True

            else:
                # Default to treating it as a batch file
                logging.warning(f"Unsupported script type: {script_path}. Treating as batch file.")

                # Create a new batch script
                new_content = f"@echo off\necho Starting Minecraft server with {max_memory}MB RAM\n"
                new_content += f"java -Xms{min_memory}M -Xmx{max_memory}M"

                # Add custom JVM args if provided
                if jvm_args:
                    new_content += f' {jvm_args}'

                new_content += f' -jar server.jar nogui\n'
                new_content += "echo Server stopped. Press any key to close window.\npause > nul\n"

                # Write new script
                with open(script_path, 'w') as f:
                    f.write(new_content)

                logging.info(f"Created new start script with Java arguments: {script_path}")
                return True

        except Exception as e:
            logging.error(f"Error editing Java arguments: {e}")
            return False