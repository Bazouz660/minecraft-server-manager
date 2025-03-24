// src/protocols/query.ts
import dgram from "dgram";

export class QueryClient {
  private host: string;
  private port: number;
  private socket: dgram.Socket | null = null;
  private sessionId: number;

  constructor(host: string, port: number) {
    this.host = host;
    this.port = port;
    // Generate a valid session ID (only use the lower 4 bits of each byte as per protocol)
    this.sessionId = Math.floor(Math.random() * 0x0f0f0f0f) & 0x0f0f0f0f;
  }

  public async getBasicStats(): Promise<any> {
    if (!this.socket) {
      this.socket = dgram.createSocket("udp4");
    }

    try {
      // Get challenge token
      const challengeToken = await this.getChallenge();

      // Create basic stats request
      const request = this.createBasicStatsRequest(challengeToken);

      // Send request and get response
      const response = await this.sendRequest(request);

      // Parse the response
      return this.parseBasicStats(response);
    } finally {
      if (this.socket) {
        this.socket.close();
        this.socket = null;
      }
    }
  }

  public async getFullStats(): Promise<any> {
    if (!this.socket) {
      this.socket = dgram.createSocket("udp4");
    }

    try {
      // Get challenge token
      const challengeToken = await this.getChallenge();

      // Create full stats request
      const request = this.createFullStatsRequest(challengeToken);

      // Send request and get response
      const response = await this.sendRequest(request);

      // Parse the response
      return this.parseFullStats(response);
    } finally {
      if (this.socket) {
        this.socket.close();
        this.socket = null;
      }
    }
  }

  private async getChallenge(): Promise<number> {
    // Create handshake packet
    const handshake = this.createHandshakePacket();

    // Send handshake packet and get response
    const response = await this.sendRequest(handshake);

    // Parse challenge token from response
    // The challenge token starts at offset 5 and is a null-terminated string
    const tokenStr = response.toString("ascii", 5, response.indexOf(0, 5));
    return parseInt(tokenStr, 10);
  }

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

  private async sendRequest(request: Buffer): Promise<Buffer> {
    if (!this.socket) {
      throw new Error("Socket is not initialized");
    }

    return new Promise((resolve, reject) => {
      this.socket!.send(
        request,
        0,
        request.length,
        this.port,
        this.host,
        (error) => {
          if (error) {
            reject(error);
            return;
          }

          // Set up a one-time message handler
          this.socket!.once("message", (message) => {
            resolve(message);
          });

          // Set a timeout to prevent hanging
          setTimeout(() => {
            // This will usually happen during shutdown, so we should handle it gracefully
            reject(new Error("Query request timed out"));
          }, 5000);
        }
      );
    });
  }

  private parseBasicStats(data: Buffer): any {
    // Skip first 5 bytes (type + session ID)
    let offset = 5;

    // Read MOTD (null-terminated string)
    const motd = this.readNullTerminatedString(data, offset);
    offset += motd.length + 1;

    // Read game type (null-terminated string)
    const gameType = this.readNullTerminatedString(data, offset);
    offset += gameType.length + 1;

    // Read map (null-terminated string)
    const map = this.readNullTerminatedString(data, offset);
    offset += map.length + 1;

    // Read numplayers (null-terminated string)
    const numPlayers = this.readNullTerminatedString(data, offset);
    offset += numPlayers.length + 1;

    // Read maxplayers (null-terminated string)
    const maxPlayers = this.readNullTerminatedString(data, offset);
    offset += maxPlayers.length + 1;

    // Read host port (little-endian short)
    const hostPort = data.readUInt16LE(offset);
    offset += 2;

    // Read host IP (null-terminated string)
    const hostIp = this.readNullTerminatedString(data, offset);

    return {
      motd,
      gameType,
      map,
      numPlayers: parseInt(numPlayers, 10),
      maxPlayers: parseInt(maxPlayers, 10),
      hostPort,
      hostIp,
    };
  }

  private parseFullStats(data: Buffer): any {
    // Skip the first 16 bytes (header + padding)
    let offset = 16;

    // Parse key-value pairs
    const kvPairs: Record<string, string> = {};

    // Read key-value pairs until we hit a zero-length key
    while (true) {
      const key = this.readNullTerminatedString(data, offset);
      offset += key.length + 1;

      if (key.length === 0) {
        break; // End of key-value section
      }

      const value = this.readNullTerminatedString(data, offset);
      offset += value.length + 1;

      kvPairs[key] = value;
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
      ...kvPairs,
      players,
    };
  }

  private readNullTerminatedString(buffer: Buffer, offset: number): string {
    const end = buffer.indexOf(0, offset);
    return buffer.toString("utf8", offset, end !== -1 ? end : undefined);
  }
}
