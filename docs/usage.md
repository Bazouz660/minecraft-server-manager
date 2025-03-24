# Usage Guide

## Main Interface

![Main Interface](../assets/screenshots/main-screen.png)

1. **Status Bar**: Shows the current server state, player count, and uptime
2. **Control Buttons**: Start, stop, and restart the server
3. **Log Display**: Shows server manager logs
4. **Settings**: Configure the application

## Starting the Server

The server will start automatically when a player tries to join. You can also:

1. Click the "Start Server" button
2. The server console will appear in a separate window
3. The status will change from "STARTING" to "RUNNING" when the server is ready

## Stopping the Server

1. Click the "Stop Server" button
2. The server will shut down gracefully via RCON
3. Status will change to "OFFLINE" when complete

## Automatic Shutdown

The server will automatically shut down after the configured inactivity period (default: 10 minutes) with no players online.

## Wake-on-Demand

1. When the server is offline, the manager listens for incoming connections
2. When a player tries to join (not just ping), the server starts automatically
3. Players will need to try connecting again after the server has started

## Viewing Logs

The main window shows logs from the server manager. To view the Minecraft server logs:

1. Look at the separate console window that opens when the server starts
2. Check the `logs/latest.log` file in your server directory

## Changing Settings

1. Click the "Settings" button
2. Modify settings in the tabs: Server, Timeouts, RCON, GUI
3. Click "Save" to apply changes
