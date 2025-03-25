// src/server-manager.ts
import { EventEmitter } from "events";
import { ServerProcessManager } from "./services/server-process";
import { ServerStateManager } from "./services/server-state";
import { MinecraftServerListener } from "./services/server-listener";
import { QueryClient } from "./protocols/query";
import type { ServerStats, FullServerStats } from "./protocols/query";
import { RconClient } from "./protocols/rcon";

export interface ServerManagerOptions {
  // Server details
  serverPath: string;
  startScript?: string | null;
  javaPath?: string;
  serverJarFile?: string;
  maxMemory?: string;

  // Network settings
  queryHost?: string;
  queryPort?: number;
  serverPort?: number;
  rconHost?: string;
  rconPort?: number;
  rconPassword?: string;

  // Feature settings
  inactivityTimeout?: number;
  wakeOnDemandEnabled?: boolean;
  autoRestartOnCrash?: boolean;
}

export class MinecraftServerManager extends EventEmitter {
  // Core services
  private processManager: ServerProcessManager;
  private stateManager: ServerStateManager;
  private serverListener: MinecraftServerListener;

  // Network clients
  private queryClient: QueryClient;
  private rconClient: RconClient;

  // Settings
  private options: ServerManagerOptions;
  private wakeOnDemandEnabled: boolean;
  private autoRestartOnCrash: boolean;
  private pendingStart: boolean = false;

  constructor(options: ServerManagerOptions) {
    super();

    this.options = {
      ...options,
      queryHost: options.queryHost || "localhost",
      queryPort: options.queryPort || 25565,
      serverPort: options.serverPort || 25565,
      rconHost: options.rconHost || "localhost",
      rconPort: options.rconPort || 25575,
      rconPassword: options.rconPassword || "",
      inactivityTimeout: options.inactivityTimeout || 0,
      wakeOnDemandEnabled: options.wakeOnDemandEnabled || false,
      autoRestartOnCrash: options.autoRestartOnCrash || false,
    };

    // Set feature flags
    this.wakeOnDemandEnabled = this.options.wakeOnDemandEnabled || false;
    this.autoRestartOnCrash = this.options.autoRestartOnCrash || false;

    // Create instances of our services with better logging configuration
    this.queryClient = new QueryClient(
      this.options.queryHost!,
      this.options.queryPort!,
      { logLevel: "info" } // Only show info and higher level logs
    );

    this.rconClient = new RconClient(
      this.options.rconHost!,
      this.options.rconPort!,
      this.options.rconPassword!
    );

    this.processManager = new ServerProcessManager({
      serverPath: this.options.serverPath,
      startScript: this.options.startScript,
      javaPath: this.options.javaPath,
      serverJarFile: this.options.serverJarFile,
      maxMemory: this.options.maxMemory,
    });

    this.stateManager = new ServerStateManager(
      this.queryClient,
      30000, // Check server state every 30 seconds
      this.options.inactivityTimeout
    );

    this.serverListener = new MinecraftServerListener({
      port: this.options.serverPort!,
    });

    // Wire up events
    this.setupEventHandlers();

    // Start monitoring server state
    this.stateManager.startMonitoring();

    // Start server listener if wake-on-demand is enabled
    if (this.wakeOnDemandEnabled) {
      this.startWakeOnDemand();
    }

    // Add a special event handler for crash detection that works across components
    this.processManager.on("serverCrashed", (errorMessage: string) => {
      console.log("Server crash detected in process manager, updating state");

      // Mark the server as crashed in the state manager
      this.stateManager.setCrashDetected(true);

      // Set the server status to offline
      this.stateManager.setServerStatus("offline");

      // Tell the query client the server is offline to reduce error noise
      this.updateQueryClientServerState(false);

      // Make sure process is terminated
      this.processManager.forceKill();

      // Emit the crash event for UI notification
      this.emit("serverCrashed", errorMessage);

      // If auto-restart on crash is enabled, attempt restart
      if (this.autoRestartOnCrash) {
        console.log("Auto-restart on crash is enabled, scheduling restart");

        // Wait 5 seconds before attempting restart
        setTimeout(() => {
          console.log("Attempting auto-restart after crash");
          this.stateManager.setCrashDetected(false); // Clear crash detection
          this.start().catch((err) => {
            console.error("Failed to auto-restart server after crash:", err);
          });
        }, 5000);
      }
    });
  }

  /**
   * Reset server state to offline and kill any hanging process
   * This is useful when the server gets stuck in an inconsistent state
   */
  public async resetServerState(): Promise<boolean> {
    console.log("Manually resetting server state");

    // Force kill any running server process
    if (this.processManager.isRunning()) {
      this.processManager.forceKill();
    }

    // Clear crash detection if it was set
    this.stateManager.setCrashDetected(false);

    // Set server status to offline
    this.stateManager.setServerStatus("offline");

    // Tell query client server is offline
    this.updateQueryClientServerState(false);

    // Wait a moment for everything to settle
    await new Promise((resolve) => setTimeout(resolve, 1000));

    return true;
  }

  /**
   * Update the query client's known server state
   */
  private updateQueryClientServerState(online: boolean): void {
    if (this.queryClient) {
      this.queryClient.setServerKnownState(online);
    }
  }

  /**
   * Check if the server is actually running and available
   * This combines process status and server query status
   */
  public isRunning(): boolean {
    // Get current state
    const currentState = this.stateManager.getState();

    // If server is in 'online' state, trust that
    if (currentState.status === "online") {
      return true;
    }

    // If server is in 'starting' state, check for too long in this state
    if (currentState.status === "starting" && currentState.startTime) {
      const startingDuration = Date.now() - currentState.startTime.getTime();

      // If starting for over 5 minutes with no success, probably not going to work
      if (
        startingDuration > 300000 &&
        currentState.lastErrorCount &&
        currentState.lastErrorCount > 10
      ) {
        console.log(
          "Server has been 'starting' for too long with errors, considering it not running"
        );
        return false;
      }
    }

    // If server is offline or stopping, it's not running
    if (
      currentState.status === "offline" ||
      currentState.status === "stopping"
    ) {
      return false;
    }

    // Default to process manager's state
    return this.processManager.isRunning();
  }

  /**
   * Check if the server is in the process of shutting down
   */
  public isShuttingDown(): boolean {
    return (
      this.stateManager.isServerStopping() || this.processManager.isInShutdown()
    );
  }

  /**
   * Get the current server state with improved accuracy
   */
  public getServerState() {
    const currentState = this.stateManager.getState();

    // If crash was detected, keep the state as offline regardless of process state
    if (currentState.crashDetected) {
      return currentState;
    }

    // If the server is in transition (starting/stopping), ensure the process state is considered
    if (currentState.status === "starting") {
      // If the process isn't running but state is "starting",
      // we might have had an error during startup
      if (
        !this.processManager.isRunning() &&
        currentState.lastStatusChange &&
        Date.now() - currentState.lastStatusChange.getTime() > 60000
      ) {
        // 1 minute

        console.log(
          "Process not running but state is starting - fixing state to offline"
        );
        this.stateManager.setServerStatus("offline");
        return this.stateManager.getState();
      }

      // If starting for too long without success, mark as failed
      if (
        currentState.startTime &&
        Date.now() - currentState.startTime.getTime() > 300000 && // 5 minutes
        currentState.lastErrorCount &&
        currentState.lastErrorCount > 10
      ) {
        console.log(
          "Server has been starting for too long with errors - fixing state to offline"
        );
        this.stateManager.setServerStatus("offline");
        return this.stateManager.getState();
      }
    } else if (currentState.status === "stopping") {
      // If the process isn't running but state is "stopping",
      // we should update to offline
      if (
        !this.processManager.isRunning() &&
        currentState.lastStatusChange &&
        Date.now() - currentState.lastStatusChange.getTime() > 30000
      ) {
        // 30 seconds

        console.log(
          "Process not running but state is stopping - fixing state to offline"
        );
        this.stateManager.setServerStatus("offline");
        return this.stateManager.getState();
      }
    } else if (currentState.status === "online") {
      // If the state is online but the process is not running,
      // we need to fix the state
      if (!this.processManager.isRunning()) {
        console.log(
          "State is online but process is not running - fixing state to offline"
        );
        this.stateManager.setServerStatus("offline");
        return this.stateManager.getState();
      }
    } // Modify the offline state check
    else if (currentState.status === "offline") {
      // IMPORTANT: Only correct state if we're SURE the process is running AND responsive
      // This will prevent the loop of state changes
      if (this.processManager.isRunning()) {
        // Extra validation - check if process has been running for over 2 minutes
        // This gives it time to start up and prevents flip-flopping states
        if (
          currentState.lastStatusChange &&
          Date.now() - currentState.lastStatusChange.getTime() > 120000
        ) {
          // Check if the process is actually responsive or just defunct
          this.processManager
            .isProcessResponsive()
            .then((responsive) => {
              if (responsive) {
                console.log(
                  "Process running and responsive but state is offline - fixing state to starting"
                );
                this.stateManager.setServerStatus("starting");
              } else {
                console.log(
                  "Process appears to be running but is not responsive - keeping state as offline"
                );
                // Attempt to kill the unresponsive process
                this.processManager.forceKill();
              }
            })
            .catch((error) => {
              console.error("Error checking process responsiveness:", error);
            });
        }
      }
    }

    return currentState;
  }

  /**
   * Start the server with improved error handling
   */
  public async start(): Promise<boolean> {
    if (this.isRunning() || this.pendingStart) {
      return true; // Already running or starting
    }

    this.pendingStart = true;

    try {
      // Stop the listener if it's running
      await this.stopWakeOnDemand();

      // Set server status to starting - do this BEFORE starting the process
      this.stateManager.setServerStatus("starting");

      // Tell the query client that we're starting up (prevent error noise during startup)
      this.updateQueryClientServerState(false);

      // Start the process
      const success = await this.processManager.start();

      if (!success) {
        this.stateManager.setServerStatus("offline");

        // Update query client state
        this.updateQueryClientServerState(false);

        // Restart listener if wake-on-demand is enabled
        if (this.wakeOnDemandEnabled) {
          await this.startWakeOnDemand();
        }
      } else {
        // Ensure the state manager knows the server is starting
        // This reinforces the starting state even if a query check happened between
        // the first state update and the process actually starting
        this.stateManager.setServerStatus("starting");

        // We're in starting state, but query might still fail until fully started
        this.updateQueryClientServerState(false);
      }

      this.pendingStart = false;
      return success;
    } catch (error) {
      console.error("Error starting server:", error);
      this.stateManager.setServerStatus("offline");

      // Update query client state
      this.updateQueryClientServerState(false);

      // Restart listener if wake-on-demand is enabled
      if (this.wakeOnDemandEnabled) {
        await this.startWakeOnDemand();
      }

      this.pendingStart = false;
      return false;
    }
  }

  /**
   * Stop the server with improved error handling
   */
  public async stop(): Promise<boolean> {
    if (!this.isRunning()) {
      return true; // Already stopped
    }

    try {
      // Set server status to stopping BEFORE stopping the process
      this.stateManager.setServerStatus("stopping");

      // Tell the query client that we're stopping (prevent error noise during shutdown)
      this.updateQueryClientServerState(false);

      // Stop the process
      const success = await this.processManager.stop();

      // If the server is still running, force kill it
      if (this.processManager.isRunning()) {
        this.processManager.forceKill();
      } else {
        // If the process is confirmed stopped, update the state
        this.stateManager.setServerStatus("offline");

        // Update query client state
        this.updateQueryClientServerState(false);
      }

      // Start listener if wake-on-demand is enabled
      if (this.wakeOnDemandEnabled) {
        await this.startWakeOnDemand();
      }

      return success;
    } catch (error) {
      console.error("Error stopping server:", error);

      // If the server is still running, force kill it
      if (this.processManager.isRunning()) {
        this.processManager.forceKill();
      }

      // Update the state to offline since we forced the process to stop
      this.stateManager.setServerStatus("offline");

      // Update query client state
      this.updateQueryClientServerState(false);

      // Start listener if wake-on-demand is enabled
      if (this.wakeOnDemandEnabled) {
        await this.startWakeOnDemand();
      }

      return false;
    }
  }

  /**
   * Send a command to the server via RCON
   */
  public async sendCommand(command: string): Promise<string> {
    if (!this.isRunning()) {
      throw new Error("Server is not running");
    }

    try {
      // First try RCON
      try {
        await this.rconClient.connect();
        const response = await this.rconClient.sendCommand(command);
        await this.rconClient.disconnect();
        return response;
      } catch (rconError) {
        console.warn(
          "RCON command failed, falling back to process stdin:",
          rconError
        );

        // Fall back to process stdin
        const success = this.processManager.sendCommand(command);
        if (!success) {
          throw new Error("Failed to send command to server");
        }
        return "Command sent (no response available)";
      }
    } catch (error) {
      console.error("Error sending command:", error);
      throw error;
    }
  }

  /**
   * Get basic server statistics
   */
  public async getBasicStats(): Promise<ServerStats> {
    if (!this.isRunning()) {
      return { online: false };
    }

    try {
      return await this.queryClient.getBasicStats();
    } catch (error) {
      console.error("Error getting basic stats:", error);

      // If the server is running but we can't query it, return a basic online status
      if (this.processManager.isRunning()) {
        return { online: true };
      }

      return { online: false };
    }
  }

  /**
   * Get detailed server statistics
   */
  public async getFullStats(): Promise<FullServerStats> {
    if (!this.isRunning()) {
      return { online: false };
    }

    try {
      return await this.queryClient.getFullStats();
    } catch (error) {
      console.error("Error getting full stats:", error);

      // If the server is running but we can't query it, return a basic online status
      if (this.processManager.isRunning()) {
        return { online: true };
      }

      return { online: false };
    }
  }

  /**
   * Extra diagnostic method to check server connectivity
   */
  public async checkServerConnectivity(): Promise<{
    processRunning: boolean;
    processResponsive: boolean;
    queryResponding: boolean;
  }> {
    // Check process status
    const processRunning = this.processManager.isRunning();
    const processResponsive = await this.processManager.isProcessResponsive();

    // Try to query server directly
    let queryResponding = false;
    try {
      const stats = await this.queryClient.getBasicStats();
      queryResponding = stats.online === true;
    } catch (error) {
      console.error("Server connectivity check - query failed:", error);
      queryResponding = false;
    }

    // Log the result
    console.log(
      `Server connectivity check: Process running=${processRunning}, ` +
        `Process responsive=${processResponsive}, Query responding=${queryResponding}`
    );

    return {
      processRunning,
      processResponsive,
      queryResponding,
    };
  }

  /**
   * Set the inactivity timeout for auto-shutdown
   */
  public setInactivityTimeout(minutes: number): void {
    this.stateManager.setInactivityTimeout(minutes);
  }

  /**
   * Get the current inactivity timeout
   */
  public getInactivityTimeout(): number {
    return this.stateManager.getInactivityTimeout();
  }

  /**
   * Check if wake-on-demand is enabled
   */
  public isWakeOnDemandEnabled(): boolean {
    return this.wakeOnDemandEnabled;
  }

  /**
   * Enable or disable wake-on-demand
   */
  public async setWakeOnDemandEnabled(enabled: boolean): Promise<void> {
    this.wakeOnDemandEnabled = enabled;

    if (enabled && !this.isRunning()) {
      await this.startWakeOnDemand();
    } else if (!enabled) {
      await this.stopWakeOnDemand();
    }
  }

  /**
   * Update the server state handler for status changes
   */
  private setupEventHandlers(): void {
    // Process manager events
    this.processManager.on("started", () => {
      console.log("Server process started");
      // Ensure state is set to starting
      this.stateManager.setServerStatus("starting");
      // Tell query client server is starting up
      this.updateQueryClientServerState(false);
      this.emit("serverStarted");
    });

    // Process manager events
    this.processManager.on("started", () => {
      console.log("Server process started");
      // Ensure state is set to starting
      this.stateManager.setServerStatus("starting");
      // Tell query client server is starting up
      this.updateQueryClientServerState(false);
      this.emit("serverStarted");
    });

    // New event for server fully started detection
    this.processManager.on("serverFullyStarted", () => {
      console.log("Server detected as fully started from logs");
      // This helps update the state faster than waiting for query
      this.stateManager.setServerStatus("online");
      // Tell query client server is now online
      this.updateQueryClientServerState(true);
      this.emit("serverFullyStarted");
    });

    this.processManager.on("stopped", (code) => {
      console.log(`Server process stopped with code ${code}`);

      // Always update state to offline when the process stops
      this.stateManager.setServerStatus("offline");
      // Tell query client server is offline
      this.updateQueryClientServerState(false);

      // Check if this was an unexpected stop
      if (!this.stateManager.isServerStopping() && this.autoRestartOnCrash) {
        console.log("Server crashed, attempting to restart...");
        this.start().catch((err) => {
          console.error("Failed to restart server after crash:", err);
        });
      }

      this.emit("serverStopped", code);
    });

    this.processManager.on("serverOutput", (line) => {
      this.emit("serverOutput", line);
    });

    this.processManager.on("serverError", (line) => {
      this.emit("serverError", line);
    });

    // State manager events
    this.stateManager.on("statusChanged", (state) => {
      console.log(`Server status changed to ${state.status}`);

      // Update query client with current state to reduce error noise
      this.updateQueryClientServerState(state.status === "online");

      // Cross-validate with process manager
      if (state.status === "offline" && this.processManager.isRunning()) {
        console.log(
          "State is offline but process is running - correcting state to starting"
        );
        this.stateManager.setServerStatus("starting");
      } else if (
        state.status === "online" &&
        !this.processManager.isRunning()
      ) {
        console.log(
          "State is online but process is not running - correcting state to offline"
        );
        this.stateManager.setServerStatus("offline");
      }

      this.emit("statusChanged", state);
    });

    this.stateManager.on("inactivityTimeout", async (state) => {
      console.log("Inactivity timeout reached, shutting down server");
      this.emit("inactivityTimeout", state);

      try {
        await this.stop();
      } catch (error) {
        console.error("Error shutting down server after inactivity:", error);
      }
    });

    // New event handler for too many errors
    this.stateManager.on("tooManyErrors", async (state) => {
      console.log("Too many consecutive query errors, checking process status");

      // Check if process is still running
      if (!this.processManager.isRunning()) {
        console.log("Process is not running, fixing state to offline");
        this.stateManager.setServerStatus("offline");
      } else {
        console.log("Process is still running despite query errors");

        // Process might be hung - consider restarting it
        if (this.autoRestartOnCrash) {
          console.log(
            "Auto-restart is enabled, restarting server due to query errors"
          );
          try {
            await this.stop();
            setTimeout(() => {
              this.start().catch((err) => {
                console.error(
                  "Failed to restart server after query errors:",
                  err
                );
              });
            }, 5000); // Give it 5 seconds before restarting
          } catch (error) {
            console.error("Error restarting server after query errors:", error);
          }
        }
      }
    });

    // Server listener events
    this.serverListener.on("connectionDetected", async (info) => {
      console.log(
        `Minecraft client connection detected from ${info.address}:${info.port}, starting server...`
      );
      this.emit("connectionDetected", info);

      if (this.wakeOnDemandEnabled && !this.isRunning() && !this.pendingStart) {
        try {
          await this.start();
        } catch (error) {
          console.error(
            "Error starting server after connection detection:",
            error
          );
        }
      }
    });
  }

  /**
   * Start the wake-on-demand listener
   */
  private async startWakeOnDemand(): Promise<void> {
    if (this.isRunning() || this.serverListener.isRunning()) {
      return;
    }

    try {
      await this.serverListener.start();
      console.log("Wake-on-demand listener started");
    } catch (error) {
      console.error("Failed to start wake-on-demand listener:", error);
    }
  }

  /**
   * Stop the wake-on-demand listener
   */
  private async stopWakeOnDemand(): Promise<void> {
    if (!this.serverListener.isRunning()) {
      return;
    }

    this.serverListener.stop();
  }

  /**
   * Clean up resources when shutting down
   */
  public async cleanup(): Promise<void> {
    // Stop server monitoring
    this.stateManager.stopMonitoring();

    // Stop wake-on-demand listener
    await this.stopWakeOnDemand();

    // Disconnect RCON
    try {
      await this.rconClient.disconnect();
    } catch (e) {
      // Ignore disconnection errors
    }

    // Close query client
    this.queryClient.close();

    // If server is running, stop it
    if (this.isRunning()) {
      await this.stop();
    }

    console.log("Server manager cleanup complete");
  }
}
