// src/protocols/rcon.ts
import net from "net";
import { EventEmitter } from "events";

// RCON Protocol Constants
const PACKET_TYPE = {
  COMMAND: 2,
  AUTH: 3,
  RESPONSE_VALUE: 0,
  AUTH_RESPONSE: 2,
};

export class RconClient extends EventEmitter {
  private host: string;
  private port: number;
  private password: string;
  private socket: net.Socket | null = null;
  private authenticated: boolean = false;
  private requestId: number = 0;
  private connectionTimeout: number = 5000; // 5 seconds timeout
  private maxRetries: number = 2;
  private pendingResponses: Map<
    number,
    {
      resolve: (value: string) => void;
      reject: (error: Error) => void;
      timer: NodeJS.Timeout;
      buffer: string;
    }
  > = new Map();

  constructor(host: string, port: number, password: string) {
    super();
    this.host = host;
    this.port = port;
    this.password = password;
  }

  /**
   * Connect to the RCON server
   */
  public async connect(retries = this.maxRetries): Promise<boolean> {
    if (this.isConnected()) {
      return true; // Already connected
    }

    return new Promise((resolve, reject) => {
      let connectionAttempted = false;

      // Create a new socket
      this.socket = net.createConnection(
        {
          host: this.host,
          port: this.port,
          timeout: this.connectionTimeout,
        },
        async () => {
          connectionAttempted = true;

          // Connection established, now authenticate
          try {
            const authSuccess = await this.authenticate();
            resolve(authSuccess);
          } catch (error) {
            this.disconnect();

            // If we have retries left, try again
            if (retries > 0) {
              console.log(
                `Retrying RCON connection (${retries} retries left)...`
              );
              try {
                const success = await this.connect(retries - 1);
                resolve(success);
              } catch (retryError) {
                reject(retryError);
              }
            } else {
              reject(error);
            }
          }
        }
      );

      // Set up event handlers
      this.socket.on("error", (error) => {
        console.error("RCON socket error:", error);
        this.authenticated = false;

        if (!connectionAttempted) {
          // If we haven't attempted to connect yet, this is a connection error
          if (retries > 0) {
            console.log(
              `Retrying RCON connection (${retries} retries left)...`
            );
            this.disconnect();
            this.connect(retries - 1)
              .then(resolve)
              .catch(reject);
          } else {
            reject(error);
          }
        } else {
          // Otherwise emit the error
          this.emit("error", error);
        }
      });

      this.socket.on("timeout", () => {
        console.error("RCON connection timed out");
        if (!connectionAttempted) {
          this.disconnect();
          if (retries > 0) {
            console.log(
              `Retrying RCON connection (${retries} retries left)...`
            );
            this.connect(retries - 1)
              .then(resolve)
              .catch(reject);
          } else {
            reject(new Error("RCON connection timed out"));
          }
        } else {
          this.emit("timeout");
        }
      });

      this.socket.on("close", () => {
        this.authenticated = false;
        this.socket = null;
        this.emit("close");

        // Reject any pending responses
        for (const [id, { reject, timer }] of this.pendingResponses.entries()) {
          clearTimeout(timer);
          reject(new Error("RCON connection closed"));
          this.pendingResponses.delete(id);
        }
      });

      this.socket.on("data", (data) => {
        this.handleResponse(data);
      });
    });
  }

  /**
   * Disconnect from the RCON server
   */
  public async disconnect(): Promise<void> {
    if (this.socket && !this.socket.destroyed) {
      this.socket.end();
      this.socket = null;
    }
    this.authenticated = false;

    // Reject any pending responses
    for (const [id, { reject, timer }] of this.pendingResponses.entries()) {
      clearTimeout(timer);
      reject(new Error("RCON disconnected"));
      this.pendingResponses.delete(id);
    }
  }

  /**
   * Check if connected to the RCON server
   */
  public isConnected(): boolean {
    return this.socket !== null && !this.socket.destroyed && this.authenticated;
  }

  /**
   * Send a command to the server
   */
  public async sendCommand(
    command: string,
    retries = this.maxRetries
  ): Promise<string> {
    if (!this.isConnected()) {
      try {
        await this.connect();
      } catch (error) {
        throw new Error(`Failed to connect to RCON server: ${error.message}`);
      }
    }

    try {
      // Generate a unique request ID
      const requestId = ++this.requestId;

      // Create and send the packet
      const packet = this.createPacket(requestId, PACKET_TYPE.COMMAND, command);
      return await this.sendPacket(requestId, packet);
    } catch (error) {
      console.error("Error sending RCON command:", error);

      // If we're still connected, but the command failed, try again
      if (this.isConnected() && retries > 0) {
        console.log(`Retrying RCON command (${retries} retries left)...`);
        return this.sendCommand(command, retries - 1);
      }

      // If we're not connected, try to reconnect and then retry
      if (!this.isConnected() && retries > 0) {
        console.log(
          `Reconnecting for RCON command (${retries} retries left)...`
        );
        try {
          await this.connect();
          return this.sendCommand(command, retries - 1);
        } catch (reconnectError) {
          throw new Error(
            `Failed to reconnect to RCON server: ${reconnectError.message}`
          );
        }
      }

      throw error;
    }
  }

  /**
   * Authenticate with the RCON server
   */
  private async authenticate(): Promise<boolean> {
    if (!this.socket || this.socket.destroyed) {
      throw new Error("Not connected to RCON server");
    }

    // Generate a unique request ID
    const requestId = ++this.requestId;

    // Create the authentication packet
    const packet = this.createPacket(
      requestId,
      PACKET_TYPE.AUTH,
      this.password
    );

    try {
      // Send the auth packet and wait for response
      await this.sendPacket(requestId, packet);
      this.authenticated = true;
      return true;
    } catch (error) {
      this.authenticated = false;
      throw new Error(`RCON authentication failed: ${error.message}`);
    }
  }

  /**
   * Send a packet and wait for response
   */
  private async sendPacket(requestId: number, packet: Buffer): Promise<string> {
    if (!this.socket || this.socket.destroyed) {
      throw new Error("Not connected to RCON server");
    }

    return new Promise((resolve, reject) => {
      // Set up a timeout
      const timer = setTimeout(() => {
        if (this.pendingResponses.has(requestId)) {
          const { buffer } = this.pendingResponses.get(requestId)!;
          this.pendingResponses.delete(requestId);

          // If we have any data received, resolve with that instead of timing out
          if (buffer.length > 0) {
            resolve(buffer);
          } else {
            reject(new Error("RCON command timed out"));
          }
        }
      }, 10000); // 10 second timeout

      // Add to pending responses
      this.pendingResponses.set(requestId, {
        resolve,
        reject,
        timer,
        buffer: "",
      });

      // Send the packet
      this.socket.write(packet, (error) => {
        if (error) {
          if (this.pendingResponses.has(requestId)) {
            clearTimeout(this.pendingResponses.get(requestId)!.timer);
            this.pendingResponses.delete(requestId);
          }
          reject(error);
        }
      });
    });
  }

  /**
   * Handle a response from the server
   */
  private handleResponse(data: Buffer): void {
    try {
      // Parse each packet in the response
      let offset = 0;
      while (offset < data.length) {
        // Check if we have enough data for the packet header
        if (offset + 4 > data.length) {
          break;
        }

        // Read packet size
        const size = data.readInt32LE(offset);

        // Check if we have the complete packet
        if (offset + 4 + size > data.length) {
          break;
        }

        // Parse the packet
        const id = data.readInt32LE(offset + 4);
        const type = data.readInt32LE(offset + 8);

        // Calculate body end position (size includes id, type, and body length)
        const bodyEnd = offset + 4 + size - 2; // Subtract 2 for the null terminators

        // Read the body (excluding the two null terminators)
        const body = data.toString("utf8", offset + 12, bodyEnd);

        // Handle the response
        if (
          type === PACKET_TYPE.RESPONSE_VALUE ||
          type === PACKET_TYPE.AUTH_RESPONSE
        ) {
          if (this.pendingResponses.has(id)) {
            const { resolve, timer, buffer } = this.pendingResponses.get(id)!;

            // Append to existing buffer
            const newBuffer = buffer + body;

            // Check if this is the final packet for this request
            if (body.length === 0 || type === PACKET_TYPE.AUTH_RESPONSE) {
              // Final packet, resolve the promise
              clearTimeout(timer);
              this.pendingResponses.delete(id);
              resolve(newBuffer);
            } else {
              // Update the buffer for future packets
              this.pendingResponses.set(id, {
                ...this.pendingResponses.get(id)!,
                buffer: newBuffer,
              });
            }
          }
        }

        // Move to the next packet
        offset += 4 + size;
      }
    } catch (error) {
      console.error("Error handling RCON response:", error);
    }
  }

  /**
   * Create an RCON packet
   */
  private createPacket(id: number, type: number, body: string): Buffer {
    // Calculate the packet size (length of body + 10 bytes for ID, type, and two null terminators)
    const size = Buffer.byteLength(body) + 10;

    // Create a buffer for the packet
    const packet = Buffer.alloc(size + 4); // +4 for the size field itself

    // Write packet size (little-endian)
    packet.writeInt32LE(size, 0);

    // Write request ID (little-endian)
    packet.writeInt32LE(id, 4);

    // Write packet type (little-endian)
    packet.writeInt32LE(type, 8);

    // Write body
    packet.write(body, 12);

    // Write two null bytes at the end
    packet.writeInt8(0, size + 2);
    packet.writeInt8(0, size + 3);

    return packet;
  }
}
