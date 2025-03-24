// src/server-manager.ts
import { spawn, ChildProcess } from "child_process";
import { join } from "path";
import fs from "fs";
import { QueryClient } from "./protocols/query";

export class MinecraftServerManager {
  private serverProcess: ChildProcess | null = null;
  private serverPath: string;
  private startScript: string | null;
  private javaPath: string;
  private serverJarFile: string;
  private maxMemory: string;
  private shutdownInProgress: boolean = false;

  // Auto-shutdown properties
  private emptyStartTime: number | null = null;
  private inactivityTimeout: number = 0; // Time in minutes before shutdown (0 = disabled)
  private inactivityCheckInterval: NodeJS.Timeout | null = null;
  private queryClient: QueryClient | null = null;

  constructor(options: {
    serverPath: string;
    startScript?: string | null;
    javaPath?: string;
    serverJarFile?: string;
    maxMemory?: string;
    inactivityTimeout?: number;
    queryClient?: QueryClient;
  }) {
    this.serverPath = options.serverPath;
    this.startScript = options.startScript || null;
    this.javaPath = options.javaPath || "java";
    this.serverJarFile = options.serverJarFile || "server.jar";
    this.maxMemory = options.maxMemory || "2G";
    this.inactivityTimeout = options.inactivityTimeout || 0;
    this.queryClient = options.queryClient || null;
  }

  public isRunning(): boolean {
    return this.serverProcess !== null && !this.serverProcess.killed;
  }

  public isShuttingDown(): boolean {
    return this.shutdownInProgress;
  }

  public async start(): Promise<boolean> {
    if (this.isRunning()) {
      return true; // Server is already running
    }

    // Check if the server directory exists
    if (!fs.existsSync(this.serverPath)) {
      throw new Error(`Server directory not found: ${this.serverPath}`);
    }

    try {
      if (this.startScript) {
        // Use start.bat if provided
        const scriptPath = join(this.serverPath, this.startScript);

        if (!fs.existsSync(scriptPath)) {
          throw new Error(`Start script not found: ${scriptPath}`);
        }

        console.log(`Starting server using script: ${scriptPath}`);

        // Create a temporary batch file that will call our actual batch file
        // This helps handle paths with spaces and also adds automatic continuation after server stop
        const tempBatContent = `@echo off
cd /d "${this.serverPath}"
call "${this.startScript}"
exit
`;
        const tempBatPath = join(process.cwd(), "temp_launcher.bat");

        try {
          fs.writeFileSync(tempBatPath, tempBatContent, "utf8");
          console.log(`Created temporary launcher: ${tempBatPath}`);
          console.log(`Launcher content: ${tempBatContent}`);

          // Execute the temporary batch file
          this.serverProcess = spawn(tempBatPath, [], {
            stdio: ["pipe", "pipe", "pipe"],
          });

          // Clean up the temporary file when the server exits
          this.serverProcess.on("close", () => {
            try {
              if (fs.existsSync(tempBatPath)) {
                fs.unlinkSync(tempBatPath);
                console.log(`Removed temporary launcher: ${tempBatPath}`);
              }
            } catch (error) {
              console.error("Error removing temporary launcher:", error);
            }
          });
        } catch (error) {
          console.error("Error creating temporary launcher:", error);
          throw error;
        }
      } else {
        // Fallback to direct Java launch
        const jarPath = join(this.serverPath, this.serverJarFile);

        if (!fs.existsSync(jarPath)) {
          throw new Error(`Server JAR file not found: ${jarPath}`);
        }

        console.log(`Starting server using Java: ${jarPath}`);

        // Start the Minecraft server process directly with Java
        this.serverProcess = spawn(
          this.javaPath,
          [`-Xmx${this.maxMemory}`, "-jar", this.serverJarFile, "nogui"],
          {
            cwd: this.serverPath,
            stdio: ["pipe", "pipe", "pipe"],
          }
        );
      }

      // Log output from the server
      this.serverProcess.stdout?.on("data", (data) => {
        console.log(`[SERVER]: ${data.toString()}`);
      });

      this.serverProcess.stderr?.on("data", (data) => {
        console.error(`[SERVER ERROR]: ${data.toString()}`);
      });

      // Handle process exit
      this.serverProcess.on("close", (code) => {
        console.log(`Server process exited with code ${code}`);
        this.serverProcess = null;
        this.stopInactivityChecker(); // Ensure checker is stopped when server stops
      });

      // Start the inactivity checker if enabled
      if (this.inactivityTimeout > 0 && this.queryClient) {
        // Give the server some time to start up before checking player count
        setTimeout(() => {
          this.startInactivityChecker();
        }, 60000); // Wait 1 minute for server to fully start
      }

      return true;
    } catch (error) {
      console.error("Failed to start Minecraft server:", error);
      return false;
    }
  }

  public async stop(): Promise<boolean> {
    if (!this.isRunning() || !this.serverProcess) {
      this.shutdownInProgress = false;
      return true; // Server is not running
    }

    try {
      // Set shutdown flag
      this.shutdownInProgress = true;

      // Stop the inactivity checker
      this.stopInactivityChecker();

      // Send 'stop' command to the server's stdin
      this.serverProcess.stdin?.write("stop\n");

      // Handle "Press any key to continue" in batch files by sending a key press
      if (this.startScript) {
        // Wait a bit for the server to initiate shutdown
        setTimeout(() => {
          if (this.serverProcess && this.serverProcess.stdin) {
            // Send enter key to continue
            this.serverProcess.stdin.write("\n");
          }
        }, 2000);
      }

      // Wait for the server to shut down gracefully
      return new Promise((resolve) => {
        const timeout = setTimeout(() => {
          // Force kill if taking too long
          if (this.serverProcess) {
            console.log(
              "Server shutdown taking too long, force killing process"
            );
            this.serverProcess.kill();
            this.serverProcess = null;
          }
          this.shutdownInProgress = false;
          resolve(true);
        }, 30000); // 30 seconds timeout

        this.serverProcess?.on("close", () => {
          clearTimeout(timeout);
          this.serverProcess = null;
          this.shutdownInProgress = false;
          resolve(true);
        });
      });
    } catch (error) {
      console.error("Failed to stop Minecraft server:", error);
      // Force kill the process
      if (this.serverProcess) {
        this.serverProcess.kill();
        this.serverProcess = null;
      }
      this.shutdownInProgress = false;
      return false;
    }
  }

  // Auto-shutdown methods
  public getInactivityTimeout(): number {
    return this.inactivityTimeout;
  }

  public setInactivityTimeout(minutes: number): void {
    const wasEnabled = this.inactivityTimeout > 0;
    this.inactivityTimeout = minutes;

    if (this.inactivityTimeout > 0 && this.isRunning()) {
      if (this.inactivityCheckInterval) {
        this.stopInactivityChecker();
      }
      this.startInactivityChecker();
      console.log(`Auto-shutdown set to ${minutes} minutes of inactivity`);
    } else if (wasEnabled) {
      this.stopInactivityChecker();
      console.log("Auto-shutdown disabled");
    }
  }

  public startInactivityChecker(): void {
    if (
      this.inactivityTimeout <= 0 ||
      !this.queryClient ||
      this.inactivityCheckInterval
    ) {
      return; // Auto-shutdown is disabled or already running
    }

    this.emptyStartTime = null; // Reset the timer

    // Check every minute
    this.inactivityCheckInterval = setInterval(async () => {
      await this.checkInactivity();
    }, 60000); // Check every minute

    console.log(
      `Started inactivity checker (timeout: ${this.inactivityTimeout} minutes)`
    );
  }

  public stopInactivityChecker(): void {
    if (this.inactivityCheckInterval) {
      clearInterval(this.inactivityCheckInterval);
      this.inactivityCheckInterval = null;
      this.emptyStartTime = null;
      console.log("Stopped inactivity checker");
    }
  }

  private async checkInactivity(): Promise<void> {
    if (
      !this.isRunning() ||
      !this.queryClient ||
      this.inactivityTimeout <= 0 ||
      this.shutdownInProgress
    ) {
      return;
    }

    try {
      // Get server stats to check player count
      const stats = await this.queryClient.getBasicStats();
      const playerCount = stats.numPlayers || 0;

      console.log(`[AUTO-SHUTDOWN] Current player count: ${playerCount}`);

      if (playerCount === 0) {
        // Server is empty
        if (this.emptyStartTime === null) {
          // Just became empty, start the timer
          this.emptyStartTime = Date.now();
          console.log(
            "[AUTO-SHUTDOWN] Server is empty, starting inactivity timer"
          );
        } else {
          // Check if timeout has been reached
          const emptyTime = (Date.now() - this.emptyStartTime) / 60000; // Convert to minutes

          console.log(
            `[AUTO-SHUTDOWN] Server has been empty for ${emptyTime.toFixed(
              2
            )} minutes`
          );

          if (emptyTime >= this.inactivityTimeout) {
            console.log(
              `[AUTO-SHUTDOWN] Timeout reached (${this.inactivityTimeout} minutes), shutting down server`
            );
            await this.stop();
          }
        }
      } else {
        // Server has players, reset the timer
        if (this.emptyStartTime !== null) {
          console.log(
            "[AUTO-SHUTDOWN] Players joined, resetting inactivity timer"
          );
          this.emptyStartTime = null;
        }
      }
    } catch (error) {
      console.error("[AUTO-SHUTDOWN] Error checking server inactivity:", error);
      // Don't count errors as activity - if there's a temporary error, we still want to shut down eventually
    }
  }
}
