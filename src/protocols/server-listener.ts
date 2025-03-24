// src/protocols/server-listener.ts
import net from "net";

// Simple implementation of Minecraft's protocol to respond to server list pings
export class MinecraftListener {
  private server: net.Server | null = null;
  private port: number;
  private startCallback: () => Promise<void>;
  private isStarting: boolean = false;

  constructor(port: number, startCallback: () => Promise<void>) {
    this.port = port;
    this.startCallback = startCallback;
  }

  public start(): Promise<void> {
    if (this.server) {
      return Promise.resolve();
    }

    return new Promise((resolve, reject) => {
      try {
        this.server = net.createServer((socket) => {
          this.handleConnection(socket);
        });

        this.server.on("error", (err) => {
          console.error("MinecraftListener error:", err);
          if ((err as any).code === "EADDRINUSE") {
            console.log(
              `Port ${this.port} is in use, assuming server is already running`
            );
            this.stop();
          }
          reject(err);
        });

        this.server.listen(this.port, () => {
          console.log(`MinecraftListener started on port ${this.port}`);
          resolve();
        });
      } catch (error) {
        console.error("Failed to start MinecraftListener:", error);
        reject(error);
      }
    });
  }

  public stop(): void {
    if (this.server) {
      this.server.close();
      this.server = null;
      console.log("MinecraftListener stopped");
    }
  }

  public isRunning(): boolean {
    return this.server !== null;
  }

  private async handleConnection(socket: net.Socket): Promise<void> {
    // When we get a connection, we'll receive the first packet which should be
    // either a handshake or a legacy ping request

    // Set a timeout in case the client doesn't send data
    socket.setTimeout(10000);
    socket.on("timeout", () => {
      socket.end();
    });

    socket.once("data", async (data) => {
      try {
        // If this is the first connection and server isn't starting yet
        if (!this.isStarting) {
          this.isStarting = true;
          console.log("Connection detected, starting server...");

          // Send a friendly message to the client
          this.respondWithStartingMessage(socket, data);

          // Start the server
          try {
            await this.startCallback();
          } catch (error) {
            console.error(
              "Failed to start server after connection detected:",
              error
            );
          }

          this.isStarting = false;
        } else {
          // If we're already starting, just send a message
          this.respondWithStartingMessage(socket, data);
        }
      } catch (error) {
        console.error("Error handling Minecraft connection:", error);
      } finally {
        // Always close the socket - the client will reconnect when our listener is gone
        // and the real server is running
        socket.end();
      }
    });
  }

  private respondWithStartingMessage(socket: net.Socket, data: Buffer): void {
    try {
      // For Minecraft 1.7+ protocols
      if (data[0] === 0x00 || data[0] === 0xfe) {
        // Simple response with a message
        // This is not fully protocol-compliant but should work for most clients
        const response = {
          version: { name: "1.21.4", protocol: 769 },
          players: { max: 20, online: 0, sample: [] },
          description: {
            text: "§e§lServer is starting up...\n§fPlease wait and try again in a moment.",
          },
        };

        // Create response packet
        const jsonResponse = JSON.stringify(response);
        const responseBuffer = Buffer.alloc(jsonResponse.length + 5);

        // Packet ID 0x00
        responseBuffer.writeUInt8(0x00, 0);

        // String length as VarInt
        responseBuffer.writeUInt8(jsonResponse.length, 1);

        // JSON response
        responseBuffer.write(jsonResponse, 2);

        socket.write(responseBuffer);
      }
    } catch (error) {
      console.error("Error sending starting message:", error);
    }
  }
}
