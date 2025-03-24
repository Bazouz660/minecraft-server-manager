# Minecraft Server Manager

A robust, feature-rich GUI application for managing Minecraft servers with wake-on-demand functionality.

## Features

- **Wake-on-Demand**: Server starts automatically when players try to connect
- **Resource Optimization**: Server shuts down when inactive to save resources
- **Clean Interface**: User-friendly GUI with server status monitoring
- **Protocol-Aware**: Properly distinguishes between status pings and login attempts
- **Robust Error Handling**: Resilient against crashes and connection issues

## Quick Start

1. Download the latest release from the [releases page](https://github.com/Bazouz660/minecraft-server-manager/releases)
2. Place the executable in your Minecraft server directory
3. Run the application
4. Players can now connect to your server - it will start automatically!

## Running from Source

1. Clone the repository:

   ```
   git clone https://github.com/Bazouz660/minecraft-server-manager.git
   ```

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Run the application:
   ```
   python run.py
   ```

## Building the Executable

To create a standalone executable:

```
python build/build.py
```

The executable will be created in the `dist` folder.

## Configuration

The application creates a configuration file `server_config.ini` on first run with default settings. You can modify this file directly or use the Settings dialog in the application.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
