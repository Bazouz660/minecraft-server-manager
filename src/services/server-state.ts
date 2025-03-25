// src/services/server-state.ts
import { EventEmitter } from "events";
import { QueryClient, ServerStats } from "../protocols/query";

export type ServerStatus = "offline" | "starting" | "online" | "stopping";

export interface ServerState {
  status: ServerStatus;
  stats?: ServerStats;
  lastCheck: Date;
  startTime?: Date;
  stopTime?: Date;
  uptime?: number; // in seconds
  playerPeakCount?: number;
  emptyTime?: Date; // when the server became empty
  emptyDuration?: number; // in seconds
  // New fields for better state tracking
  lastStatusChange?: Date;
  lastErrorCount?: number;
  startupTimeoutExpired?: boolean;
}

export class ServerStateManager extends EventEmitter {
  private currentState: ServerState;
  private queryClient: QueryClient;
  private monitorInterval: NodeJS.Timeout | null = null;
  private checkIntervalMs: number;
  private inactivityTimeoutMins: number;
  // Constants for better state management
  private startupGracePeriodMs: number = 60000; // 1 minute grace period for startup
  private errorThreshold: number = 3; // Number of consecutive errors before changing state
  private queryCooldown: Map<string, number> = new Map(); // Cooldown for query operations
  private consecutiveErrors: number = 0;

  constructor(
    queryClient: QueryClient,
    checkIntervalMs = 30000,
    inactivityTimeoutMins = 0
  ) {
    super();
    this.queryClient = queryClient;
    this.checkIntervalMs = checkIntervalMs;
    this.inactivityTimeoutMins = inactivityTimeoutMins;

    this.currentState = {
      status: "offline",
      lastCheck: new Date(),
      lastErrorCount: 0,
    };
  }

  /**
   * Start monitoring the server state
   */
  public startMonitoring(): void {
    if (this.monitorInterval) {
      return; // Already monitoring
    }

    this.checkState(); // Check immediately

    this.monitorInterval = setInterval(() => {
      this.checkState();
    }, this.checkIntervalMs);

    console.log("Server state monitoring started");
  }

  /**
   * Stop monitoring the server state
   */
  public stopMonitoring(): void {
    if (this.monitorInterval) {
      clearInterval(this.monitorInterval);
      this.monitorInterval = null;
      console.log("Server state monitoring stopped");
    }
  }

  /**
   * Get the current server state
   */
  public getState(): ServerState {
    return { ...this.currentState };
  }

  /**
   * Check if the server is currently running
   */
  public isServerRunning(): boolean {
    return (
      this.currentState.status === "online" ||
      this.currentState.status === "starting"
    );
  }

  /**
   * Check if the server is currently stopping
   */
  public isServerStopping(): boolean {
    return this.currentState.status === "stopping";
  }

  /**
   * Set the inactivity timeout
   */
  public setInactivityTimeout(minutes: number): void {
    this.inactivityTimeoutMins = minutes;

    // If the server is empty, reset the empty timer with the new timeout
    if (
      this.currentState.emptyTime &&
      this.currentState.status === "online" &&
      this.currentState.stats?.numPlayers === 0
    ) {
      this.currentState.emptyTime = new Date();
      this.currentState.emptyDuration = 0;
    }
  }

  /**
   * Get the current inactivity timeout
   */
  public getInactivityTimeout(): number {
    return this.inactivityTimeoutMins;
  }

  /**
   * Set the server status externally (e.g., when manually starting or stopping)
   */
  public setServerStatus(status: ServerStatus): void {
    const previousStatus = this.currentState.status;

    if (status === previousStatus) {
      return; // No change
    }

    this.currentState.status = status;
    this.currentState.lastStatusChange = new Date();

    // Reset error count on explicit status change
    this.consecutiveErrors = 0;
    this.currentState.lastErrorCount = 0;

    // Reset startup timeout flag if we're not starting
    if (status !== "starting") {
      this.currentState.startupTimeoutExpired = false;
    }

    // Update timestamps based on status changes
    if (status === "starting" && previousStatus === "offline") {
      this.currentState.startTime = new Date();
      this.currentState.stopTime = undefined;
      this.currentState.uptime = 0;
      this.currentState.playerPeakCount = 0;
      this.currentState.emptyTime = undefined;
      this.currentState.emptyDuration = undefined;
    } else if (status === "stopping" && previousStatus === "online") {
      this.currentState.stopTime = new Date();
    } else if (status === "offline") {
      this.currentState.stopTime = this.currentState.stopTime || new Date();
      this.currentState.uptime = undefined;
      this.currentState.emptyTime = undefined;
      this.currentState.emptyDuration = undefined;
    }

    this.currentState.lastCheck = new Date();

    // Emit the status change event
    this.emit("statusChanged", this.currentState);
    console.log(`Server status changed to ${status} (manual update)`);
  }

  /**
   * Check if we should query the server based on its current state
   */
  private shouldPerformQuery(): boolean {
    const now = Date.now();
    const currentStatus = this.currentState.status;

    // If we recently checked, don't check again
    const lastCheckKey = `lastCheck_${currentStatus}`;
    const lastCheckTime = this.queryCooldown.get(lastCheckKey) || 0;

    if (now - lastCheckTime < 5000) {
      // 5 second cooldown between checks of the same state
      return false;
    }

    // Update last check time
    this.queryCooldown.set(lastCheckKey, now);

    // If server is starting, only check after grace period
    if (currentStatus === "starting" && this.currentState.startTime) {
      const startupTime = now - this.currentState.startTime.getTime();

      if (startupTime < this.startupGracePeriodMs) {
        if (startupTime > 10000) {
          // After 10 seconds, check occasionally
          return Math.random() < 0.3; // 30% chance to check
        }
        return false; // Don't check during first 10 seconds
      }

      // If startup has taken too long, mark the timeout as expired
      if (startupTime > 180000 && !this.currentState.startupTimeoutExpired) {
        // 3 minutes
        this.currentState.startupTimeoutExpired = true;
        console.log(
          "Server startup grace period has expired, will check status more aggressively"
        );
      }
    }

    // If server is stopping, check less frequently
    if (currentStatus === "stopping") {
      return Math.random() < 0.5; // 50% chance to check
    }

    return true;
  }

  /**
   * Check the server state via query with improved error handling
   */
  private async checkState(): Promise<void> {
    try {
      // Update check timestamp
      this.currentState.lastCheck = new Date();

      // Check if we should perform a query based on current state
      if (!this.shouldPerformQuery()) {
        return;
      }

      // Get server stats
      const stats = await this.queryClient.getBasicStats();
      const previousStatus = this.currentState.status;

      // Reset consecutive errors on successful query
      this.consecutiveErrors = 0;
      this.currentState.lastErrorCount = 0;

      if (stats.online) {
        // Server is online
        if (previousStatus === "starting" || previousStatus === "offline") {
          console.log("Server detected as online");
          this.currentState.status = "online";
          this.currentState.lastStatusChange = new Date();

          // If we were starting, and now we're online, this means the startup was successful
          if (!this.currentState.startTime) {
            this.currentState.startTime = new Date();
          }

          this.emit("statusChanged", this.currentState);
        }

        // Update stats
        this.currentState.stats = stats;

        // Update uptime
        if (this.currentState.startTime) {
          this.currentState.uptime = Math.floor(
            (new Date().getTime() - this.currentState.startTime.getTime()) /
              1000
          );
        }

        // Update player peak
        const currentPlayers = stats.numPlayers || 0;
        if (
          !this.currentState.playerPeakCount ||
          currentPlayers > this.currentState.playerPeakCount
        ) {
          this.currentState.playerPeakCount = currentPlayers;
        }

        // Check for empty server
        if (currentPlayers === 0) {
          if (!this.currentState.emptyTime) {
            // Server just became empty
            this.currentState.emptyTime = new Date();
            this.currentState.emptyDuration = 0;
            console.log("Server is empty, starting inactivity timer");
            this.emit("serverEmpty", this.currentState);
          } else {
            // Server was already empty, update duration
            this.currentState.emptyDuration = Math.floor(
              (new Date().getTime() - this.currentState.emptyTime.getTime()) /
                1000
            );

            // Check if we should auto-shutdown
            if (
              this.inactivityTimeoutMins > 0 &&
              this.currentState.emptyDuration >= this.inactivityTimeoutMins * 60
            ) {
              console.log(
                `Server has been empty for ${Math.floor(
                  this.currentState.emptyDuration / 60
                )} minutes, ` +
                  `exceeding the ${this.inactivityTimeoutMins} minute timeout`
              );
              this.emit("inactivityTimeout", this.currentState);
            }
          }
        } else if (this.currentState.emptyTime) {
          // Server was empty but now has players
          this.currentState.emptyTime = undefined;
          this.currentState.emptyDuration = undefined;
          console.log("Server is no longer empty, canceling inactivity timer");
          this.emit("serverActive", this.currentState);
        }
      } else {
        // If server was explicitly set to starting or stopping, don't override
        // this until we exceed error threshold or timeout
        if (previousStatus === "starting") {
          if (this.currentState.startupTimeoutExpired) {
            // If startup timeout expired and server is still not responding, mark as offline
            console.log(
              "Server startup timeout expired and server is not responding, marking as offline"
            );
            this.currentState.status = "offline";
            this.currentState.stats = undefined;
            this.currentState.lastStatusChange = new Date();
            this.emit("statusChanged", this.currentState);
          }
          return;
        }

        if (previousStatus === "stopping") {
          // If stopping for more than 2 minutes, mark as offline
          if (
            this.currentState.lastStatusChange &&
            Date.now() - this.currentState.lastStatusChange.getTime() > 120000
          ) {
            console.log(
              "Server has been stopping for over 2 minutes, marking as offline"
            );
            this.currentState.status = "offline";
            this.currentState.stats = undefined;
            this.currentState.lastStatusChange = new Date();
            this.emit("statusChanged", this.currentState);
          }
          return;
        }

        // Server is offline
        if (previousStatus === "online") {
          // Don't immediately mark as offline - wait for several confirmations
          // to prevent false offline detections due to temporary network hiccups
          this.consecutiveErrors++;
          if (this.consecutiveErrors >= 3) {
            // Require 3 consecutive offline confirmations
            console.log(
              "Server detected as offline (confirmed by multiple checks)"
            );
            this.currentState.status = "offline";
            this.currentState.stats = undefined;
            this.currentState.stopTime = new Date();
            this.currentState.lastStatusChange = new Date();
            this.currentState.uptime = undefined;
            this.currentState.emptyTime = undefined;
            this.currentState.emptyDuration = undefined;
            this.emit("statusChanged", this.currentState);
          } else {
            console.log(
              `Detected server offline but waiting for confirmation (${this.consecutiveErrors}/3)`
            );
          }
        }
      }
    } catch (error) {
      // Don't log the error directly here since the QueryClient will already log it properly
      // Just increment the consecutive errors counter
      this.consecutiveErrors++;
      this.currentState.lastErrorCount = this.consecutiveErrors;

      // Don't change state due to transient errors until we have multiple consecutive errors
      if (this.consecutiveErrors >= 5) {
        // Increased error threshold
        const currentStatus = this.currentState.status;

        if (currentStatus === "online") {
          // After 5 errors, we can consider the server might be having issues,
          // but still don't mark as offline yet - just log the issue
          console.log(
            `Multiple query errors (${this.consecutiveErrors}) while server is online. Keeping status as online.`
          );

          // Only mark as offline after significantly more consecutive errors
          if (this.consecutiveErrors >= 10) {
            console.log(
              "Too many consecutive errors, checking if process is still running"
            );
            this.emit("tooManyErrors", this.currentState);
          }
        } else if (
          currentStatus === "starting" &&
          this.currentState.startupTimeoutExpired
        ) {
          // If startup grace period has expired and we're still getting errors, server might be stuck
          console.log(
            "Server startup seems stuck with query errors, marking as offline"
          );
          this.currentState.status = "offline";
          this.currentState.lastStatusChange = new Date();
          this.emit("statusChanged", this.currentState);
        } else if (
          currentStatus === "stopping" &&
          this.currentState.lastStatusChange
        ) {
          // If stopping for a while and getting errors, server might be offline already
          const stoppingDuration =
            Date.now() - this.currentState.lastStatusChange.getTime();
          if (stoppingDuration > 60000) {
            // 1 minute
            console.log(
              "Server has been stopping but we're getting query errors, marking as offline"
            );
            this.currentState.status = "offline";
            this.currentState.lastStatusChange = new Date();
            this.emit("statusChanged", this.currentState);
          }
        }
      }
    }
  }
}
