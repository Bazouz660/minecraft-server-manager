// src/protocols/rcon.ts
import net from "net";

// RCON Protocol Constants
const PACKET_TYPE = {
  COMMAND: 2,
  AUTH: 3,
  RESPONSE_VALUE: 0,
  AUTH_RESPONSE: 2,
};

export class RconClient {
  private host: string;
  private port: number;
  private password: string;
  private socket: net.Socket | null = null;
  private authenticated: boolean = false;
  private requestId: number = 0;

  constructor(host: string, port: number, password: string) {
    this.host = host;
    this.port = port;
    this.password = password;
  }

  public async connect(): Promise<boolean> {
    if (this.socket && !this.socket.destroyed) {
      return true; // Already connected
    }

    return new Promise((resolve, reject) => {
      this.socket = net.createConnection(
        {
          host: this.host,
          port: this.port,
        },
        () => {
          // Connection established, now authenticate
          this.authenticate()
            .then((success) => {
              resolve(success);
            })
            .catch((error) => {
              reject(error);
            });
        }
      );

      this.socket.on("error", (error) => {
        reject(error);
      });

      this.socket.on("close", () => {
        this.authenticated = false;
        this.socket = null;
      });
    });
  }

  public async disconnect(): Promise<void> {
    if (this.socket && !this.socket.destroyed) {
      this.socket.end();
      this.socket = null;
    }
    this.authenticated = false;
  }

  public async sendCommand(command: string): Promise<string> {
    if (!this.socket || this.socket.destroyed || !this.authenticated) {
      await this.connect();
    }

    if (!this.authenticated || !this.socket) {
      throw new Error("Not authenticated with RCON server");
    }

    return new Promise((resolve, reject) => {
      // Generate a unique request ID
      const requestId = ++this.requestId;

      // Create the packet
      const packet = this.createPacket(requestId, PACKET_TYPE.COMMAND, command);

      // Set up a one-time response handler
      const responseHandler = (data: Buffer) => {
        const response = this.parsePacket(data);
        if (response.id === requestId) {
          this.socket?.removeListener("data", responseHandler);
          resolve(response.body);
        }
      };

      // Listen for the response
      this.socket.on("data", responseHandler);

      // Send the command
      this.socket.write(packet, (error) => {
        if (error) {
          this.socket?.removeListener("data", responseHandler);
          reject(error);
        }
      });

      // Set a timeout to prevent hanging
      setTimeout(() => {
        this.socket?.removeListener("data", responseHandler);
        reject(new Error("RCON command timed out"));
      }, 5000);
    });
  }

  private async authenticate(): Promise<boolean> {
    if (!this.socket || this.socket.destroyed) {
      throw new Error("Not connected to RCON server");
    }

    return new Promise((resolve, reject) => {
      // Generate a unique request ID
      const requestId = ++this.requestId;

      // Create the authentication packet
      const packet = this.createPacket(
        requestId,
        PACKET_TYPE.AUTH,
        this.password
      );

      // Set up a one-time response handler
      const authResponseHandler = (data: Buffer) => {
        const response = this.parsePacket(data);
        this.socket?.removeListener("data", authResponseHandler);

        if (response.id === requestId) {
          this.authenticated = true;
          resolve(true);
        } else {
          reject(new Error("RCON authentication failed"));
        }
      };

      // Listen for the response
      this.socket.on("data", authResponseHandler);

      // Send the auth packet
      this.socket.write(packet, (error) => {
        if (error) {
          this.socket?.removeListener("data", authResponseHandler);
          reject(error);
        }
      });

      // Set a timeout to prevent hanging
      setTimeout(() => {
        this.socket?.removeListener("data", authResponseHandler);
        reject(new Error("RCON authentication timed out"));
      }, 5000);
    });
  }

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

  private parsePacket(data: Buffer): {
    id: number;
    type: number;
    body: string;
  } {
    // Parse the packet
    const id = data.readInt32LE(4);
    const type = data.readInt32LE(8);
    const body = data.toString("utf8", 12, data.length - 2);

    return { id, type, body };
  }
}
