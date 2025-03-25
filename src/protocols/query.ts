// src/protocols/query.ts
import dgram from "dgram";
import { EventEmitter } from "events";

export interface ServerStats {
  online: boolean;
  motd?: string;
  gameType?: string;
  map?: string;
  numPlayers?: number;
  maxPlayers?: number;
  hostPort?: number;
  hostIp?: string;
}

export interface FullServerStats extends ServerStats {
  players?: string[];
  version?: string;
  plugins?: string;
  [key: string]: any;
}

export class QueryClient extends EventEmitter {
  private host: string;
  private port: number;
  private socket: dgram.Socket | null = null;
  private sessionId: number;
  private connectionTimeout = 5000; // 5 seconds timeout
  private maxRetries = 2;
  private isReady = false;

  // Rate limiting and cooldown
  private lastQueryTime: number = 0;
  private queryCooldownMs: number = 2000; // 2 second cooldown between queries
  private consecutiveFailures: number = 0;
  private failureBackoffMs: number = 0; // Increases with consecutive failures

  constructor(host: string, port: number) {
    super();
    this.host = host;
    this.port = port;
    // Generate a valid session ID (only use the lower 4 bits of each byte as per protocol)
    this.sessionId = Math.floor(Math.random() * 0x0f0f0f0f) & 0x0f0f0f0f;
  }

  /**
   * Initialize the socket for communication with better lifecycle management
   */
  private async initSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Check if socket is already initialized and valid
        if (this.socket && this.isReady) {
          return resolve(); // Socket is already good to use
        }

        // Close any existing socket first if it exists but isn't ready
        if (this.socket) {
          try {
            this.socket.removeAllListeners(); // Remove all listeners first
            this.socket.close();
          } catch (e) {
            console.log("Ignoring error when closing existing socket:", e);
            // Ignore errors on close
          }
          this.socket = null;
        }

        // Create a new socket
        this.socket = dgram.createSocket("udp4");

        // Set up error handler
        this.socket.on("error", (err) => {
          console.error("QueryClient socket error:", err);
          this.isReady = false;
          this.emit("error", err);
        });

        // Set up close handler
        this.socket.on("close", () => {
          this.isReady = false;
          this.socket = null;
          this.emit("close");
        });

        // Socket is ready to use
        this.isReady = true;
        resolve();
      } catch (error) {
        this.isReady = false;
        this.socket = null;
        reject(error);
      }
    });
  }

  /**
   * Close the socket if it's open
   */
  public close(): void {
    if (this.socket) {
      try {
        this.socket.removeAllListeners(); // Remove all listeners before closing
        this.socket.close();
      } catch (e) {
        console.log("Ignoring error when closing socket:", e);
        // Ignore errors on close
      }
      this.socket = null;
      this.isReady = false;
    }
  }

  /**
   * Check if we should retry based on rate limiting and cooldown
   */
  private shouldRetry(operationType: string): boolean {
    const now = Date.now();

    // Check if we're respecting the cooldown
    if (now - this.lastQueryTime < this.queryCooldownMs) {
      return false;
    }

    // Apply exponential backoff based on consecutive failures
    if (this.consecutiveFailures > 0) {
      const backoff = Math.min(
        60000,
        Math.pow(2, this.consecutiveFailures - 1) * 1000
      ); // Max 1 minute
      if (now - this.lastQueryTime < backoff) {
        return false;
      }
    }

    // If we have too many consecutive failures, reduce retries
    if (this.consecutiveFailures > 5) {
      console.log(
        `Too many consecutive query failures (${this.consecutiveFailures}), limiting retries`
      );
      return false;
    }

    return true;
  }

  /**
   * Track query result for rate limiting purposes
   */
  private trackQueryResult(success: boolean): void {
    this.lastQueryTime = Date.now();

    if (success) {
      // Reset failure count on success
      this.consecutiveFailures = 0;
      this.failureBackoffMs = 0;
    } else {
      // Increment failure count
      this.consecutiveFailures++;
      // Calculate backoff time based on failures (capped at 60 seconds)
      this.failureBackoffMs = Math.min(
        60000,
        Math.pow(2, this.consecutiveFailures - 1) * 1000
      );
    }
  }

  /**
   * Get basic server statistics with improved socket management
   */
  public async getBasicStats(retries = this.maxRetries): Promise<ServerStats> {
    // Check if we should limit the request based on rate limiting
    if (retries < this.maxRetries && !this.shouldRetry("basic")) {
      console.log("Skipping query retry due to rate limiting");
      return { online: false };
    }

    let socketCreated = false;
    try {
      // Create a new socket for each operation - this ensures we always have a fresh socket
      await this.initSocket();
      socketCreated = true;

      try {
        // Get challenge token
        const challengeToken = await this.getChallenge();

        // Create basic stats request
        const request = this.createBasicStatsRequest(challengeToken);

        // Send request and get response
        const response = await this.sendRequest(request);

        // Parse the response
        const result = this.parseBasicStats(response);

        // Track successful query
        this.trackQueryResult(true);

        return result;
      } catch (error) {
        // Track failed query for rate limiting
        this.trackQueryResult(false);

        // If we have retries left and should retry, try again
        if (retries > 0 && this.shouldRetry("basic")) {
          console.log(`Retrying query (${retries} retries left)...`);

          // Make sure the socket is properly closed before retrying
          if (socketCreated) {
            this.close();
          }

          return this.getBasicStats(retries - 1);
        }

        // If server may be offline, return a basic offline status
        console.error("Failed to get server stats:", error);
        return { online: false };
      }
    } catch (error) {
      // Track failed query for rate limiting
      this.trackQueryResult(false);

      console.error("Failed to initialize socket for query:", error);
      return { online: false };
    } finally {
      // Always ensure the socket is closed after the operation
      // to prevent resource leaks and ensure fresh sockets on next query
      if (socketCreated) {
        this.close();
      }
    }
  }

  /**
   * Get full server statistics with improved socket management
   */
  public async getFullStats(
    retries = this.maxRetries
  ): Promise<FullServerStats> {
    // Check if we should limit the request based on rate limiting
    if (retries < this.maxRetries && !this.shouldRetry("full")) {
      console.log("Skipping full query retry due to rate limiting");
      return { online: false };
    }

    let socketCreated = false;
    try {
      // Create a new socket for each operation
      await this.initSocket();
      socketCreated = true;

      try {
        // Get challenge token
        const challengeToken = await this.getChallenge();

        // Create full stats request
        const request = this.createFullStatsRequest(challengeToken);

        // Send request and get response
        const response = await this.sendRequest(request);

        // Parse the response
        const result = this.parseFullStats(response);

        // Track successful query
        this.trackQueryResult(true);

        return result;
      } catch (error) {
        // Track failed query for rate limiting
        this.trackQueryResult(false);

        // If we have retries left and should retry, try again
        if (retries > 0 && this.shouldRetry("full")) {
          console.log(`Retrying full query (${retries} retries left)...`);

          // Make sure the socket is properly closed before retrying
          if (socketCreated) {
            this.close();
          }

          return this.getFullStats(retries - 1);
        }

        // If server may be offline, return a basic offline status
        console.error("Failed to get full server stats:", error);
        return { online: false };
      }
    } catch (error) {
      // Track failed query for rate limiting
      this.trackQueryResult(false);

      console.error("Failed to initialize socket for full query:", error);
      return { online: false };
    } finally {
      // Always ensure the socket is closed after the operation
      if (socketCreated) {
        this.close();
      }
    }
  }

  /**
   * Get a challenge token from the server
   */
  private async getChallenge(): Promise<number> {
    // Create handshake packet
    const handshake = this.createHandshakePacket();

    // Send handshake packet and get response
    const response = await this.sendRequest(handshake);

    if (response.length < 5) {
      throw new Error("Invalid challenge response (too short)");
    }

    // Find the end of the token string
    const endIndex = response.indexOf(0, 5);
    if (endIndex === -1) {
      throw new Error("Invalid challenge response (no null terminator)");
    }

    // Parse challenge token from response
    const tokenStr = response.toString("ascii", 5, endIndex);

    try {
      const token = parseInt(tokenStr, 10);
      if (isNaN(token)) {
        throw new Error("Invalid challenge token (not a number)");
      }
      return token;
    } catch (error) {
      throw new Error(`Failed to parse challenge token: ${error.message}`);
    }
  }

  /**
   * Create a handshake packet
   */
  private createHandshakePacket(): Buffer {
    const packet = Buffer.alloc(7);

    // Magic header (0xFEFD)
    packet.writeUInt16BE(0xfefd, 0);

    // Packet type (9 for handshake)
    packet.writeUInt8(9, 2);

    // Session ID
    packet.writeInt32BE(this.sessionId, 3);

    return packet;
  }

  /**
   * Create a basic stats request packet
   */
  private createBasicStatsRequest(challengeToken: number): Buffer {
    const packet = Buffer.alloc(11);

    // Magic header (0xFEFD)
    packet.writeUInt16BE(0xfefd, 0);

    // Packet type (0 for stat)
    packet.writeUInt8(0, 2);

    // Session ID
    packet.writeInt32BE(this.sessionId, 3);

    // Challenge token
    packet.writeInt32BE(challengeToken, 7);

    return packet;
  }

  /**
   * Create a full stats request packet
   */
  private createFullStatsRequest(challengeToken: number): Buffer {
    const packet = Buffer.alloc(15);

    // Magic header (0xFEFD)
    packet.writeUInt16BE(0xfefd, 0);

    // Packet type (0 for stat)
    packet.writeUInt8(0, 2);

    // Session ID
    packet.writeInt32BE(this.sessionId, 3);

    // Challenge token
    packet.writeInt32BE(challengeToken, 7);

    // Padding (4 bytes of zeros)
    packet.writeInt32BE(0, 11);

    return packet;
  }

  /**
   * Send a request to the server and get a response
   */
  private async sendRequest(request: Buffer): Promise<Buffer> {
    if (!this.socket || !this.isReady) {
      throw new Error("Socket is not initialized");
    }

    return new Promise((resolve, reject) => {
      // Set up message handler before sending
      const messageHandler = (message: Buffer) => {
        clearTimeout(timer);
        resolve(message);
      };

      // Set up a timeout
      const timer = setTimeout(() => {
        this.socket?.removeListener("message", messageHandler);
        reject(new Error("Query request timed out"));
      }, this.connectionTimeout);

      // Set up listener
      this.socket.once("message", messageHandler);

      // Send the request
      this.socket.send(
        request,
        0,
        request.length,
        this.port,
        this.host,
        (error) => {
          if (error) {
            clearTimeout(timer);
            this.socket?.removeListener("message", messageHandler);
            reject(error);
          }
        }
      );
    });
  }

  /**
   * Parse basic server stats from a response buffer with improved error handling
   */
  private parseBasicStats(data: Buffer): ServerStats {
    try {
      if (data.length < 5) {
        throw new Error("Response too short for basic stats");
      }

      // Skip first 5 bytes (type + session ID)
      let offset = 5;

      // Validate we have enough data
      if (offset >= data.length) {
        throw new Error("Invalid basic stats response (too short)");
      }

      // Read MOTD (null-terminated string)
      const motd = this.readNullTerminatedString(data, offset);
      offset += motd.length + 1;

      // Validate we have enough data
      if (offset >= data.length) {
        return {
          online: true,
          motd,
        };
      }

      // Read game type (null-terminated string)
      const gameType = this.readNullTerminatedString(data, offset);
      offset += gameType.length + 1;

      // Validate we have enough data
      if (offset >= data.length) {
        return {
          online: true,
          motd,
          gameType,
        };
      }

      // Read map (null-terminated string)
      const map = this.readNullTerminatedString(data, offset);
      offset += map.length + 1;

      // Validate we have enough data
      if (offset >= data.length) {
        return {
          online: true,
          motd,
          gameType,
          map,
        };
      }

      // Read numplayers (null-terminated string)
      const numPlayersStr = this.readNullTerminatedString(data, offset);
      offset += numPlayersStr.length + 1;
      const numPlayers = parseInt(numPlayersStr, 10);

      // Validate we have enough data
      if (offset >= data.length) {
        return {
          online: true,
          motd,
          gameType,
          map,
          numPlayers: isNaN(numPlayers) ? 0 : numPlayers,
        };
      }

      // Read maxplayers (null-terminated string)
      const maxPlayersStr = this.readNullTerminatedString(data, offset);
      offset += maxPlayersStr.length + 1;
      const maxPlayers = parseInt(maxPlayersStr, 10);

      // Validate we have enough data for host port
      if (offset + 2 > data.length) {
        return {
          online: true,
          motd,
          gameType,
          map,
          numPlayers: isNaN(numPlayers) ? 0 : numPlayers,
          maxPlayers: isNaN(maxPlayers) ? 0 : maxPlayers,
        };
      }

      // Read host port (little-endian short)
      const hostPort = data.readUInt16LE(offset);
      offset += 2;

      // Validate we have enough data
      if (offset >= data.length) {
        return {
          online: true,
          motd,
          gameType,
          map,
          numPlayers: isNaN(numPlayers) ? 0 : numPlayers,
          maxPlayers: isNaN(maxPlayers) ? 0 : maxPlayers,
          hostPort,
        };
      }

      // Read host IP (null-terminated string)
      const hostIp = this.readNullTerminatedString(data, offset);

      return {
        online: true,
        motd,
        gameType,
        map,
        numPlayers: isNaN(numPlayers) ? 0 : numPlayers,
        maxPlayers: isNaN(maxPlayers) ? 0 : maxPlayers,
        hostPort,
        hostIp,
      };
    } catch (error) {
      console.error("Error parsing basic stats:", error);
      // Return a default response
      return { online: true };
    }
  }

  /**
   * Parse full server stats from a response buffer with improved error handling
   */
  private parseFullStats(data: Buffer): FullServerStats {
    try {
      if (data.length < 16) {
        throw new Error("Response too short for full stats");
      }

      // Skip the first 16 bytes (header + padding)
      let offset = 16;

      if (offset >= data.length) {
        return { online: true };
      }

      // Parse key-value pairs
      const kvPairs: Record<string, string> = {};

      // Read key-value pairs until we hit a zero-length key
      while (offset < data.length) {
        const key = this.readNullTerminatedString(data, offset);
        offset += key.length + 1;

        if (key.length === 0 || offset >= data.length) {
          break; // End of key-value section
        }

        const value = this.readNullTerminatedString(data, offset);
        offset += value.length + 1;

        kvPairs[key] = value;
      }

      // Skip padding
      // But check we have enough data first
      if (offset + 10 >= data.length) {
        return {
          online: true,
          ...kvPairs,
          numPlayers: parseInt(kvPairs.numplayers || "0", 10) || 0,
          maxPlayers: parseInt(kvPairs.maxplayers || "0", 10) || 0,
          players: [],
        };
      }

      // Skip 10 bytes of padding
      offset += 10;

      // Read player names
      const players: string[] = [];

      while (offset < data.length) {
        const player = this.readNullTerminatedString(data, offset);
        offset += player.length + 1;

        if (player.length === 0) {
          break; // End of player section
        }

        players.push(player);
      }

      return {
        online: true,
        ...kvPairs,
        numPlayers: parseInt(kvPairs.numplayers || "0", 10) || 0,
        maxPlayers: parseInt(kvPairs.maxplayers || "0", 10) || 0,
        players,
      };
    } catch (error) {
      console.error("Error parsing full stats:", error);
      // Return a default response
      return { online: true };
    }
  }

  /**
   * Read a null-terminated string from a buffer
   */
  private readNullTerminatedString(buffer: Buffer, offset: number): string {
    if (offset >= buffer.length) {
      return "";
    }

    const end = buffer.indexOf(0, offset);
    if (end === -1) {
      // If no null terminator is found, return the rest of the buffer as a string
      return buffer.toString("utf8", offset);
    }

    return buffer.toString("utf8", offset, end);
  }
}
