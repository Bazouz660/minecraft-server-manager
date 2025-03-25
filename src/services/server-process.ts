// src/services/server-process.ts
import { spawn, ChildProcess } from "child_process";
import { join } from "path";
import fs from "fs";
import { EventEmitter } from "events";

export interface ServerProcessOptions {
  serverPath: string;
  startScript?: string | null;
  javaPath?: string;
  serverJarFile?: string;
  maxMemory?: string;
  additionalArgs?: string[];
}

export class ServerProcessManager extends EventEmitter {
  private serverProcess: ChildProcess | null = null;
  private options: ServerProcessOptions;
  private tempFiles: string[] = [];
  private isShuttingDown: boolean = false;

  constructor(options: ServerProcessOptions) {
    super();
    this.options = {
      serverPath: options.serverPath,
      startScript: options.startScript || null,
      javaPath: options.javaPath || "java",
      serverJarFile: options.serverJarFile || "server.jar",
      maxMemory: options.maxMemory || "2G",
      additionalArgs: options.additionalArgs || [],
    };
  }

  /**
   * Check if the server process is running
   */
  public isRunning(): boolean {
    return this.serverProcess !== null && !this.serverProcess.killed;
  }

  /**
   * Check if server is in the process of shutting down
   */
  public isInShutdown(): boolean {
    return this.isShuttingDown;
  }

  /**
   * Start the server process
   */
  public async start(): Promise<boolean> {
    if (this.isRunning()) {
      console.log("Server is already running");
      return true;
    }

    // Check if server directory exists
    if (!fs.existsSync(this.options.serverPath)) {
      throw new Error(`Server directory not found: ${this.options.serverPath}`);
    }

    try {
      if (this.options.startScript) {
        // Use start script
        return this.startWithScript();
      } else {
        // Direct Java launch
        return this.startWithJava();
      }
    } catch (error) {
      console.error("Failed to start server process:", error);
      this.cleanupTempFiles();
      return false;
    }
  }

  /**
   * Stop the server process
   */
  public async stop(): Promise<boolean> {
    if (!this.isRunning() || !this.serverProcess) {
      this.isShuttingDown = false;
      return true; // Server is not running
    }

    this.isShuttingDown = true;
    this.emit("stopping");

    try {
      // Send 'stop' command to the server's stdin
      this.serverProcess.stdin?.write("stop\n");

      // Handle "Press any key to continue" in batch files by sending a key press
      if (this.options.startScript) {
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
          console.log("Server shutdown taking too long, force killing process");
          this.forceKill();
          resolve(true);
        }, 30000); // 30 seconds timeout

        this.serverProcess?.on("close", () => {
          clearTimeout(timeout);
          this.serverProcess = null;
          this.isShuttingDown = false;
          this.cleanupTempFiles();
          this.emit("stopped");
          resolve(true);
        });
      });
    } catch (error) {
      console.error("Failed to stop server gracefully:", error);
      this.forceKill();
      return false;
    }
  }

  /**
   * Force kill the server process
   */
  public forceKill(): void {
    if (this.serverProcess) {
      try {
        this.serverProcess.kill("SIGKILL");
      } catch (error) {
        console.error("Error force killing server process:", error);
      }
      this.serverProcess = null;
      this.isShuttingDown = false;
      this.cleanupTempFiles();
      this.emit("stopped");
    }
  }

  /**
   * Send a command to the server
   */
  public sendCommand(command: string): boolean {
    if (!this.isRunning() || !this.serverProcess || !this.serverProcess.stdin) {
      return false;
    }

    try {
      this.serverProcess.stdin.write(`${command}\n`);
      return true;
    } catch (error) {
      console.error("Failed to send command to server:", error);
      return false;
    }
  }

  /**
   * Start server using a startup script
   */
  private async startWithScript(): Promise<boolean> {
    const scriptPath = join(this.options.serverPath, this.options.startScript!);

    if (!fs.existsSync(scriptPath)) {
      throw new Error(`Start script not found: ${scriptPath}`);
    }

    console.log(`Starting server using script: ${scriptPath}`);

    // Create a temporary batch file that will call our actual batch file
    // This helps handle paths with spaces and adds automatic continuation after server stop
    const tempBatPath = join(process.cwd(), `temp_launcher_${Date.now()}.bat`);
    const tempBatContent = `@echo off
cd /d "${this.options.serverPath}"
call "${this.options.startScript}"
exit
`;

    try {
      fs.writeFileSync(tempBatPath, tempBatContent, "utf8");
      this.tempFiles.push(tempBatPath);
      console.log(`Created temporary launcher: ${tempBatPath}`);

      // Execute the temporary batch file
      this.serverProcess = spawn(tempBatPath, [], {
        stdio: ["pipe", "pipe", "pipe"],
      });

      this.setupProcessHandlers();
      return true;
    } catch (error) {
      console.error("Error creating temporary launcher:", error);
      this.cleanupTempFiles();
      throw error;
    }
  }

  /**
   * Start server directly with Java
   */
  private async startWithJava(): Promise<boolean> {
    const jarPath = join(this.options.serverPath, this.options.serverJarFile!);

    if (!fs.existsSync(jarPath)) {
      throw new Error(`Server JAR file not found: ${jarPath}`);
    }

    console.log(`Starting server using Java: ${jarPath}`);

    // Basic Java args
    const javaArgs = [
      `-Xmx${this.options.maxMemory}`,
      "-jar",
      this.options.serverJarFile!,
      "nogui",
    ];

    // Add any additional args
    if (this.options.additionalArgs && this.options.additionalArgs.length > 0) {
      javaArgs.push(...this.options.additionalArgs);
    }

    // Start the Minecraft server process directly with Java
    this.serverProcess = spawn(this.options.javaPath!, javaArgs, {
      cwd: this.options.serverPath,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.setupProcessHandlers();
    return true;
  }

  /**
   * Setup handlers for the server process with improved monitoring
   */
  private setupProcessHandlers(): void {
    if (!this.serverProcess) {
      return;
    }

    // Add a heartbeat timer that periodically checks if the process is still responding
    const heartbeatInterval = setInterval(() => {
      if (!this.serverProcess || this.serverProcess.killed) {
        // Process is no longer valid, clear interval
        clearInterval(heartbeatInterval);

        // If we didn't already emit a 'stopped' event, do it now
        if (this.isShuttingDown) {
          this.isShuttingDown = false;
          this.emit("stopped");
        }

        return;
      }

      // Check if process is still responsive by checking its exit code
      // Exit code is null if the process is still running
      if (this.serverProcess.exitCode !== null) {
        const exitCode = this.serverProcess.exitCode;
        console.log(
          `Process appears to have exited with code ${exitCode} but we missed the event`
        );
        clearInterval(heartbeatInterval);

        // Clean up and emit stopped event
        this.serverProcess = null;
        this.isShuttingDown = false;
        this.cleanupTempFiles();
        this.emit("stopped", exitCode);
      }
    }, 10000); // Check every 10 seconds

    // Log output from the server
    this.serverProcess.stdout?.on("data", (data) => {
      const lines = data.toString().trim().split("\n");
      lines.forEach((line: string) => {
        console.log(`[SERVER]: ${line}`);
        this.emit("serverOutput", line);

        // Detect server fully started by looking for key log messages
        if (
          line.includes("Done") &&
          (line.includes("For help, type") ||
            line.includes("seconds") ||
            line.includes("ms"))
        ) {
          this.emit("serverFullyStarted");
        }
      });
    });

    this.serverProcess.stderr?.on("data", (data) => {
      const lines = data.toString().trim().split("\n");
      lines.forEach((line: string) => {
        console.error(`[SERVER ERROR]: ${line}`);
        this.emit("serverError", line);
      });
    });

    // Handle process exit
    this.serverProcess.on("close", (code) => {
      console.log(`Server process exited with code ${code}`);
      clearInterval(heartbeatInterval);
      this.serverProcess = null;
      this.isShuttingDown = false;
      this.cleanupTempFiles();
      this.emit("stopped", code);
    });

    this.serverProcess.on("error", (error) => {
      console.error("Server process error:", error);
      this.emit("processError", error);
    });

    // Let listeners know the server has started
    this.emit("started");
  }

  /**
   * Clean up any temporary files created
   */
  private cleanupTempFiles(): void {
    this.tempFiles.forEach((file) => {
      try {
        if (fs.existsSync(file)) {
          fs.unlinkSync(file);
          console.log(`Removed temporary file: ${file}`);
        }
      } catch (error) {
        console.error(`Failed to remove temporary file ${file}:`, error);
      }
    });
    this.tempFiles = [];
  }

  /**
   * Validate if the process is actually running and responsive
   * This is more accurate than just checking if the process exists
   */
  public async isProcessResponsive(): Promise<boolean> {
    if (!this.serverProcess || this.serverProcess.killed) {
      return false;
    }

    // Check if the process has an exit code (non-null means it's exited)
    if (this.serverProcess.exitCode !== null) {
      console.log(
        `Process appears to have exited with code ${this.serverProcess.exitCode}`
      );
      return false;
    }

    // Check if the process can be communicated with
    // We'll try to get the PID which will throw if the process is defunct
    try {
      const pid = this.serverProcess.pid;
      if (!pid) {
        console.log("Process has no PID, likely not running");
        return false;
      }

      // On Windows, we can't easily check process responsiveness further
      // On Unix systems, we could send signals, but for cross-platform we'll rely on pid check

      return true;
    } catch (error) {
      console.error("Error checking process responsiveness:", error);
      return false;
    }
  }
}
