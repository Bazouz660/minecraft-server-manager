// src/server-manager.ts
import { spawn, ChildProcess } from "child_process";
import { join } from "path";
import fs from "fs";

export class MinecraftServerManager {
  private serverProcess: ChildProcess | null = null;
  private serverPath: string;
  private startScript: string | null;
  private javaPath: string;
  private serverJarFile: string;
  private maxMemory: string;
  private shutdownInProgress: boolean = false;

  constructor(options: {
    serverPath: string;
    startScript?: string | null;
    javaPath?: string;
    serverJarFile?: string;
    maxMemory?: string;
  }) {
    this.serverPath = options.serverPath;
    this.startScript = options.startScript || null;
    this.javaPath = options.javaPath || "java";
    this.serverJarFile = options.serverJarFile || "server.jar";
    this.maxMemory = options.maxMemory || "2G";
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
      });

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
}
