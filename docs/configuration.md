# Configuration Guide

The Minecraft Server Manager uses a configuration file `server_config.ini` that is created automatically on first run.

## Configuration Options

### Server Section

| Option             | Description                                 | Default   |
| ------------------ | ------------------------------------------- | --------- |
| port               | Minecraft server network port               | 25565     |
| start_command      | Command or batch file to start the server   | start.bat |
| inactivity_timeout | Seconds of no players before shutdown       | 600       |
| check_interval     | Interval in seconds to check for players    | 60        |
| startup_wait       | Seconds to wait after starting server       | 5         |
| shutdown_timeout   | Maximum seconds to wait for server shutdown | 30        |

### RCON Section

| Option   | Description                                  | Default   |
| -------- | -------------------------------------------- | --------- |
| enabled  | Enable RCON functionality                    | true      |
| host     | RCON host (usually localhost)                | localhost |
| port     | RCON port (must match server.properties)     | 25575     |
| password | RCON password (must match server.properties) | changeme  |
| timeout  | RCON connection timeout in seconds           | 3         |

### GUI Section

| Option           | Description                                 | Default |
| ---------------- | ------------------------------------------- | ------- |
| auto_scroll_logs | Automatically scroll logs to newest entries | true    |
| theme            | GUI theme                                   | default |
| update_interval  | Status update interval in milliseconds      | 1000    |
| max_log_lines    | Maximum number of log lines to display      | 1000    |

### System Section

| Option     | Description                   | Default |
| ---------- | ----------------------------- | ------- |
| debug_mode | Enable detailed debug logging | false   |

## Example Configuration

```ini
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
password = your_secure_password_here
timeout = 3

[GUI]
auto_scroll_logs = true
theme = default
update_interval = 1000
max_log_lines = 1000

[System]
debug_mode = false
```
