// src/index.ts
import { Elysia } from "elysia";
import { staticPlugin } from "@elysiajs/static";
import { MinecraftServerManager } from "./server-manager";
import { join } from "path";
import { readFileSync, existsSync, writeFileSync } from "fs";
import { examineStartBat, fixStartBat } from "./utils/start-bat-helper";

// Load configuration
const config = {
  server: {
    path: process.env.MC_SERVER_PATH || "C:\\games\\Rlcraft Dregora Server",
    startScript: process.env.MC_START_SCRIPT || "start.bat",
    jarFile: process.env.MC_SERVER_JAR || "server.jar",
    javaPath: process.env.JAVA_PATH || "java",
    maxMemory: process.env.MC_MAX_MEMORY || "2G",
  },
  network: {
    rconHost: process.env.RCON_HOST || "localhost",
    rconPort: parseInt(process.env.RCON_PORT || "25575", 10),
    rconPassword: process.env.RCON_PASSWORD || "cacamerde123",
    queryHost: process.env.QUERY_HOST || "localhost",
    queryPort: parseInt(process.env.QUERY_PORT || "25565", 10),
    serverPort: parseInt(process.env.SERVER_PORT || "25565", 10),
  },
  web: {
    port: parseInt(process.env.WEB_PORT || "3000", 10),
  },
  autoShutdown: {
    enabled: process.env.AUTO_SHUTDOWN_ENABLED === "true",
    timeout: parseInt(process.env.AUTO_SHUTDOWN_TIMEOUT || "30", 10), // Default 30 minutes
  },
  wakeOnDemand: {
    enabled: process.env.WAKE_ON_DEMAND_ENABLED === "true",
  },
  advanced: {
    autoRestartOnCrash: process.env.AUTO_RESTART_ON_CRASH === "true",
  },
};

// Initialize server manager
const serverManager = new MinecraftServerManager({
  // Server settings
  serverPath: config.server.path,
  startScript: config.server.startScript,
  javaPath: config.server.javaPath,
  serverJarFile: config.server.jarFile,
  maxMemory: config.server.maxMemory,

  // Network settings
  rconHost: config.network.rconHost,
  rconPort: config.network.rconPort,
  rconPassword: config.network.rconPassword,
  queryHost: config.network.queryHost,
  queryPort: config.network.queryPort,
  serverPort: config.network.serverPort,

  // Feature settings
  inactivityTimeout: config.autoShutdown.enabled
    ? config.autoShutdown.timeout
    : 0,
  wakeOnDemandEnabled: config.wakeOnDemand.enabled,
  autoRestartOnCrash: config.advanced.autoRestartOnCrash,
});

// Handle process termination to clean up resources
process.on("SIGINT", async () => {
  console.log("Shutting down server manager...");
  await serverManager.cleanup();
  process.exit(0);
});

process.on("SIGTERM", async () => {
  console.log("Shutting down server manager...");
  await serverManager.cleanup();
  process.exit(0);
});

// Create Elysia app
const app = new Elysia()
  .get("/", () => {
    // Serve the simple HTML directly
    try {
      const filePath = "./src/public/index.html";

      if (!existsSync(filePath)) {
        // If the file doesn't exist, return a simple HTML page
        return new Response(
          `
          <!DOCTYPE html>
          <html>
          <head>
            <title>Minecraft Server Manager</title>
            <style>
              body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
              button { padding: 10px; margin: 5px; }
              .response { background-color: #f0f0f0; padding: 10px; margin-top: 10px; border-radius: 5px; }
            </style>
          </head>
          <body>
            <h1>Minecraft Server Manager</h1>
            <p>Simple fallback interface:</p>
            <div>
              <button id="statusBtn">Check Status</button>
              <button id="startBtn">Start Server</button>
              <button id="stopBtn">Stop Server</button>
              <div id="statusResponse" class="response">Status will appear here...</div>
            </div>
            <script>
              document.getElementById('statusBtn').addEventListener('click', async () => {
                try {
                  const response = await fetch('/api/status');
                  const data = await response.json();
                  document.getElementById('statusResponse').textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                  document.getElementById('statusResponse').textContent = 'Error: ' + error.message;
                }
              });
              
              document.getElementById('startBtn').addEventListener('click', async () => {
                try {
                  const response = await fetch('/api/start', { method: 'POST' });
                  const data = await response.json();
                  document.getElementById('statusResponse').textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                  document.getElementById('statusResponse').textContent = 'Error: ' + error.message;
                }
              });
              
              document.getElementById('stopBtn').addEventListener('click', async () => {
                try {
                  const response = await fetch('/api/stop', { method: 'POST' });
                  const data = await response.json();
                  document.getElementById('statusResponse').textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                  document.getElementById('statusResponse').textContent = 'Error: ' + error.message;
                }
              });
            </script>
          </body>
          </html>
        `,
          {
            headers: {
              "Content-Type": "text/html",
            },
          }
        );
      }

      const html = readFileSync(filePath, "utf-8");
      return new Response(html, {
        headers: {
          "Content-Type": "text/html",
        },
      });
    } catch (error) {
      console.error("Error serving HTML:", error);
      return new Response(
        `
        <html><body>
          <h1>Minecraft Server Manager</h1>
          <p>Error loading interface. Please check server logs.</p>
        </body></html>
      `,
        {
          headers: {
            "Content-Type": "text/html",
          },
        }
      );
    }
  })
  .use(
    staticPlugin({
      assets: "./src/public",
      prefix: "/static",
    })
  )

  .get("/api/examine-start-bat", async () => {
    const content = await examineStartBat(
      config.server.path,
      config.server.startScript || "start.bat"
    );
    return { content };
  })

  .post("/api/fix-start-bat", async () => {
    const success = fixStartBat(
      config.server.path,
      config.server.startScript || "start.bat"
    );
    return {
      success,
      message: success
        ? "Start script was fixed. A backup was created with .backup extension."
        : "Failed to fix start script. Check the server logs for details.",
    };
  })

  .get("/api/create-launcher", async () => {
    try {
      // Create a direct launcher that doesn't rely on the start.bat
      const jarPath = join(config.server.path, config.server.jarFile);

      // Simple launcher that just launches the JAR directly
      const launcherContent = `@echo off
echo Starting Minecraft Server with direct launcher...
cd /d "${config.server.path}"
"${config.server.javaPath}" -Xmx${config.server.maxMemory} -jar "${config.server.jarFile}" nogui
pause`;

      const launcherPath = join(config.server.path, "direct_launcher.bat");
      writeFileSync(launcherPath, launcherContent, "utf8");

      return {
        success: true,
        message: "Created direct launcher at: " + launcherPath,
        path: launcherPath,
      };
    } catch (error) {
      return {
        success: false,
        message: `Error creating launcher: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  // API endpoints
  .get("/api/config", () => {
    // Return a sanitized version of the configuration (without sensitive info)
    return {
      server: {
        path: config.server.path,
        startScript: config.server.startScript || "(Using direct Java launch)",
        jarFile: config.server.jarFile,
      },
      network: {
        rconHost: config.network.rconHost,
        rconPort: config.network.rconPort,
        queryHost: config.network.queryHost,
        queryPort: config.network.queryPort,
        serverPort: config.network.serverPort,
      },
      autoShutdown: {
        enabled: serverManager.getInactivityTimeout() > 0,
        timeout: serverManager.getInactivityTimeout(),
      },
      wakeOnDemand: {
        enabled: serverManager.isWakeOnDemandEnabled(),
      },
      advanced: {
        autoRestartOnCrash: config.advanced.autoRestartOnCrash,
      },
    };
  })

  .get("/api/status", async () => {
    // Get the current server state which includes process and query information
    const serverState = serverManager.getServerState();

    // Determine the actual server status based on state and process info
    let effectiveStatus = serverState.status;
    const isProcessRunning = serverManager.isRunning();
    const isShuttingDown = serverManager.isShuttingDown();

    // If the process is running but state doesn't reflect that, override
    if (isProcessRunning && effectiveStatus === "offline") {
      effectiveStatus = "starting";
    }

    // If the process is not running but state says it's online, override
    if (!isProcessRunning && effectiveStatus === "online") {
      effectiveStatus = "stopping";
    }

    // If we're in shutdown process, make sure status reflects that
    if (
      isShuttingDown &&
      (effectiveStatus === "online" || effectiveStatus === "starting")
    ) {
      effectiveStatus = "stopping";
    }

    return {
      status: effectiveStatus,
      isRunning: isProcessRunning,
      isShuttingDown: isShuttingDown,
      serverInfo: serverState.stats,
      uptime: serverState.uptime,
      playerPeakCount: serverState.playerPeakCount,
      emptyDuration: serverState.emptyDuration,
      // Add additional information to help with debugging
      stateLastUpdated: serverState.lastStatusChange,
      lastCheck: serverState.lastCheck,
      errorCount: serverState.lastErrorCount || 0,
    };
  })

  .post("/api/start", async () => {
    if (serverManager.isRunning()) {
      return { success: true, message: "Server is already running" };
    }

    try {
      const success = await serverManager.start();
      return {
        success,
        message: success
          ? "Server started successfully"
          : "Failed to start server",
      };
    } catch (error) {
      return {
        success: false,
        message: `Error starting server: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .post("/api/stop", async () => {
    if (!serverManager.isRunning()) {
      return { success: true, message: "Server is not running" };
    }

    try {
      const success = await serverManager.stop();
      return {
        success,
        message: success
          ? "Server stopped successfully"
          : "Failed to stop server",
      };
    } catch (error) {
      return {
        success: false,
        message: `Error stopping server: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .post("/api/command", async ({ body }) => {
    if (!serverManager.isRunning()) {
      return { success: false, message: "Server is not running" };
    }

    const { command } = body as { command: string };

    if (!command) {
      return { success: false, message: "No command provided" };
    }

    try {
      const response = await serverManager.sendCommand(command);
      return { success: true, response };
    } catch (error) {
      return {
        success: false,
        message: `Error executing command: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .get("/api/info", async () => {
    if (!serverManager.isRunning()) {
      return { success: false, message: "Server is not running" };
    }

    try {
      const info = await serverManager.getFullStats();
      return { success: true, info };
    } catch (error) {
      return {
        success: false,
        message: `Error getting server info: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .get("/api/auto-shutdown", () => {
    return {
      enabled: serverManager.getInactivityTimeout() > 0,
      timeout: serverManager.getInactivityTimeout(),
    };
  })

  .post("/api/auto-shutdown", async ({ body }) => {
    const { enabled, timeout } = body as { enabled: boolean; timeout: number };

    // Validate timeout (between 1 minute and 24 hours)
    const validTimeout = Math.max(
      1,
      Math.min(parseInt(String(timeout), 10) || 30, 1440)
    );

    // Update the server manager
    serverManager.setInactivityTimeout(enabled ? validTimeout : 0);

    return {
      success: true,
      enabled: serverManager.getInactivityTimeout() > 0,
      timeout: serverManager.getInactivityTimeout(),
    };
  })

  .get("/api/wake-on-demand", () => {
    return {
      enabled: serverManager.isWakeOnDemandEnabled(),
    };
  })

  .post("/api/wake-on-demand", async ({ body }) => {
    const { enabled } = body as { enabled: boolean };

    try {
      await serverManager.setWakeOnDemandEnabled(enabled);

      return {
        success: true,
        enabled: serverManager.isWakeOnDemandEnabled(),
        message: enabled
          ? "Wake-on-demand enabled. Server will start automatically when a client tries to connect."
          : "Wake-on-demand disabled.",
      };
    } catch (error) {
      return {
        success: false,
        message: `Error setting wake-on-demand: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .get("/api/diagnostics", async () => {
    // Check server connectivity
    const connectivity = await serverManager.checkServerConnectivity();

    // Get current state
    const state = serverManager.getServerState();

    return {
      success: true,
      connectivity,
      state,
      message: `Diagnostics completed at ${new Date().toISOString()}`,
    };
  })

  // Reset server state (for when it gets stuck)
  .post("/api/reset-state", async () => {
    try {
      const success = await serverManager.resetServerState();
      return {
        success,
        message: success
          ? "Server state has been reset to offline"
          : "Failed to reset server state",
      };
    } catch (error) {
      return {
        success: false,
        message: `Error resetting server state: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  })

  .listen(config.web.port);

console.log(
  `Minecraft Server Manager is running at http://localhost:${config.web.port}`
);
