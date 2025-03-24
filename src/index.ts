// src/index.ts
import { Elysia } from "elysia";
import { staticPlugin } from "@elysiajs/static";
import { MinecraftServerManager } from "./server-manager";
import { RconClient } from "./protocols/rcon";
import { QueryClient } from "./protocols/query";
import { join } from "path";

// Load configuration
const config = {
  server: {
    path:
      process.env.MC_SERVER_PATH || "C:\\games\\Rlcraft Dregora Server - Copie",
    startScript: process.env.MC_START_SCRIPT || "start.bat",
    jarFile: process.env.MC_SERVER_JAR || "server.jar",
    javaPath: process.env.JAVA_PATH || "java",
    maxMemory: process.env.MC_MAX_MEMORY || "2G",
  },
  rcon: {
    host: process.env.RCON_HOST || "localhost",
    port: parseInt(process.env.RCON_PORT || "25575", 10),
    password: process.env.RCON_PASSWORD || "cacamerde123",
  },
  query: {
    host: process.env.QUERY_HOST || "localhost",
    port: parseInt(process.env.QUERY_PORT || "25565", 10),
  },
  web: {
    port: parseInt(process.env.WEB_PORT || "3000", 10),
  },
  // Add auto-shutdown configuration
  autoShutdown: {
    enabled: process.env.AUTO_SHUTDOWN_ENABLED === "true",
    timeout: parseInt(process.env.AUTO_SHUTDOWN_TIMEOUT || "1", 10), // Default 1 minutes
  },
};

const queryClient = new QueryClient(config.query.host, config.query.port);

// When initializing the server manager, pass the queryClient and inactivity timeout
const serverManager = new MinecraftServerManager({
  serverPath: config.server.path,
  startScript: config.server.startScript,
  javaPath: config.server.javaPath,
  serverJarFile: config.server.jarFile,
  maxMemory: config.server.maxMemory,
  inactivityTimeout: config.autoShutdown.enabled
    ? config.autoShutdown.timeout
    : 0,
  queryClient: queryClient, // Pass the queryClient instance
});

const rconClient = new RconClient(
  config.rcon.host,
  config.rcon.port,
  config.rcon.password
);

import { examineStartBat, fixStartBat } from "./start-bat-helper";
import { readFileSync, existsSync, writeFileSync } from "fs";
import { join } from "path";

// Create Elysia app
const app = new Elysia()
  .get("/", () => {
    // Serve the simple HTML directly
    try {
      const filePath = "./src/public/index.html";

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

  // API routes
  .get("/api/config", () => {
    // Return a sanitized version of the configuration (without sensitive info)
    return {
      server: {
        path: config.server.path,
        startScript: config.server.startScript || "(Using direct Java launch)",
        jarFile: config.server.jarFile,
        // Don't expose memory settings as they might be sensitive
      },
      rcon: {
        host: config.rcon.host,
        port: config.rcon.port,
        // Don't expose the password
      },
      query: {
        host: config.query.host,
        port: config.query.port,
      },
    };
  })

  .get("/api/status", async () => {
    const isRunning = serverManager.isRunning();

    let serverInfo = null;
    if (isRunning) {
      try {
        serverInfo = await queryClient.getBasicStats();
      } catch (error) {
        console.error("Failed to get server stats:", error);
        // Don't let query failure affect the status response
        // This typically happens during shutdown
      }
    }

    return {
      isRunning,
      serverInfo,
      shutdownInProgress: serverManager.isShuttingDown(),
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
      await rconClient.connect();
      const response = await rconClient.sendCommand(command);
      await rconClient.disconnect();

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
      const info = await queryClient.getFullStats();
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

  // Add these API endpoints after your existing endpoints
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

  .listen(config.web.port);

console.log(
  `Minecraft Server Manager is running at http://localhost:${config.web.port}`
);
