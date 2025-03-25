// src/services/server-listener.ts
import net from "net";
import { EventEmitter } from "events";

/**
 * A minimal implementation of the Minecraft network protocol
 * just enough to respond to server list pings and detect connection
 * attempts so we can start the server on demand
 */
export class MinecraftServerListener extends EventEmitter {
  private server: net.Server | null = null;
  private port: number;
  private isListening: boolean = false;
  private activeConnections: Set<net.Socket> = new Set();
  private messageOfTheDay: string;
  private serverVersion: string;
  private protocol: number;
  private maxPlayers: number;

  constructor({
    port = 25565,
    motd = "§e§lServer Starting Up...§r\n§fPlease wait a moment",
    version = "1.21.4",
    protocol = 769,
    maxPlayers = 20,
  } = {}) {
    super();
    this.port = port;
    this.messageOfTheDay = motd;
    this.serverVersion = version;
    this.protocol = protocol;
    this.maxPlayers = maxPlayers;
  }

  /**
   * Start listening for connections
   */
  public async start(): Promise<void> {
    if (this.isListening) {
      return; // Already listening
    }

    return new Promise((resolve, reject) => {
      try {
        this.server = net.createServer((socket) => {
          this.handleConnection(socket);
        });

        this.server.on("error", (err) => {
          console.error("MinecraftListener error:", err);
          const typedError = err as NodeJS.ErrnoException;

          if (typedError.code === "EADDRINUSE") {
            console.log(
              `Port ${this.port} is in use, assuming server is already running`
            );
            this.stop();
          }

          if (!this.isListening) {
            // Only reject if we haven't successfully started listening yet
            reject(err);
          } else {
            this.emit("error", err);
          }
        });

        this.server.listen(this.port, () => {
          this.isListening = true;
          console.log(`MinecraftListener started on port ${this.port}`);
          this.emit("listening", this.port);
          resolve();
        });
      } catch (error) {
        console.error("Failed to start MinecraftListener:", error);
        this.isListening = false;
        reject(error);
      }
    });
  }

  /**
   * Stop listening for connections
   */
  public stop(): void {
    // Close all active connections
    for (const socket of this.activeConnections) {
      try {
        socket.end();
      } catch (e) {
        // Ignore errors on close
      }
    }
    this.activeConnections.clear();

    // Close the server
    if (this.server) {
      this.server.close(() => {
        console.log("MinecraftListener stopped");
        this.emit("stopped");
      });
      this.server = null;
      this.isListening = false;
    }
  }

  /**
   * Check if the listener is running
   */
  public isRunning(): boolean {
    return this.isListening;
  }

  /**
   * Update the MOTD (message of the day)
   */
  public setMotd(motd: string): void {
    this.messageOfTheDay = motd;
  }

  /**
   * Set server details
   */
  public setServerDetails({
    motd,
    version,
    protocol,
    maxPlayers,
  }: {
    motd?: string;
    version?: string;
    protocol?: number;
    maxPlayers?: number;
  } = {}): void {
    if (motd !== undefined) this.messageOfTheDay = motd;
    if (version !== undefined) this.serverVersion = version;
    if (protocol !== undefined) this.protocol = protocol;
    if (maxPlayers !== undefined) this.maxPlayers = maxPlayers;
  }

  /**
   * Handle incoming connections
   */
  private handleConnection(socket: net.Socket): void {
    this.activeConnections.add(socket);

    // Set a timeout in case the client doesn't send data
    socket.setTimeout(10000);

    socket.on("timeout", () => {
      socket.end();
      this.activeConnections.delete(socket);
    });

    socket.on("error", (err) => {
      console.error("Socket error in MinecraftListener:", err);
      this.activeConnections.delete(socket);
    });

    socket.on("close", () => {
      this.activeConnections.delete(socket);
    });

    // Wait for data from the client
    socket.once("data", (data) => {
      try {
        this.handlePacket(socket, data);
      } catch (error) {
        console.error("Error handling Minecraft packet:", error);
      } finally {
        // Always emit connection detected event so the server can be started
        this.emit("connectionDetected", {
          address: socket.remoteAddress,
          port: socket.remotePort,
        });
      }
    });
  }

  /**
   * Handle Minecraft packets
   */
  private handlePacket(socket: net.Socket, data: Buffer): void {
    // Handle different protocol versions
    if (data.length > 0) {
      if (data[0] === 0xfe) {
        // Legacy ping (1.6 and below)
        this.handleLegacyPing(socket);
      } else {
        // Modern protocol (1.7+)
        this.handleModernPing(socket, data);
      }
    }
  }

  /**
   * Handle modern protocol pings (1.7+)
   */
  private handleModernPing(socket: net.Socket, data: Buffer): void {
    try {
      // Send a status response
      const response = {
        version: {
          name: this.serverVersion,
          protocol: this.protocol,
        },
        players: {
          max: this.maxPlayers,
          online: 0,
          sample: [],
        },
        description: {
          text: this.messageOfTheDay,
        },
        // Optionally add a favicon here if desired
      };

      // Create response packet
      const jsonResponse = JSON.stringify(response);

      // Calculate packet length (includes string length prefix)
      const packetLength = jsonResponse.length + 5;

      // Write packet
      const responseBuffer = Buffer.alloc(packetLength);
      let offset = 0;

      // Packet length
      this.writeVarInt(responseBuffer, packetLength - 5, offset);
      offset += this.varIntLength(packetLength - 5);

      // Packet ID (0x00 for status response)
      responseBuffer.writeUInt8(0x00, offset++);

      // JSON string length as VarInt
      this.writeVarInt(responseBuffer, jsonResponse.length, offset);
      offset += this.varIntLength(jsonResponse.length);

      // JSON response
      responseBuffer.write(jsonResponse, offset);

      socket.write(responseBuffer);
    } catch (error) {
      console.error("Error handling modern ping:", error);
    } finally {
      // Close the connection after sending the response
      socket.end();
    }
  }

  /**
   * Handle legacy protocol pings (1.6 and below)
   */
  private handleLegacyPing(socket: net.Socket): void {
    try {
      // Legacy protocol response format
      const response = [
        "§1",
        "127", // Protocol version
        this.serverVersion,
        this.messageOfTheDay,
        "0", // Current players
        `${this.maxPlayers}`, // Max players
      ].join("\0");

      // Prefix with 0xFF and the length as a short
      const responseBuffer = Buffer.alloc(response.length + 3);
      responseBuffer.writeUInt8(0xff, 0);
      responseBuffer.writeUInt16BE(response.length, 1);
      responseBuffer.write(response, 3, "utf16le");

      socket.write(responseBuffer);
    } catch (error) {
      console.error("Error handling legacy ping:", error);
    } finally {
      // Close the connection after sending the response
      socket.end();
    }
  }

  /**
   * Write a VarInt to a buffer
   */
  private writeVarInt(buffer: Buffer, value: number, offset: number): number {
    let currentOffset = offset;
    do {
      let temp = value & 0x7f;
      value >>>= 7;
      if (value !== 0) {
        temp |= 0x80;
      }
      buffer.writeUInt8(temp, currentOffset++);
    } while (value !== 0);
    return currentOffset - offset;
  }

  /**
   * Calculate the length of a VarInt
   */
  private varIntLength(value: number): number {
    if ((value & 0xffffff80) === 0) {
      return 1;
    } else if ((value & 0xffffc000) === 0) {
      return 2;
    } else if ((value & 0xffe00000) === 0) {
      return 3;
    } else if ((value & 0xf0000000) === 0) {
      return 4;
    }
    return 5;
  }
}
