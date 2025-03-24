// src/public/script.js
document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const statusText = document.getElementById("status-text");
  const serverInfo = document.getElementById("server-info");
  const motdText = document.getElementById("motd-text");
  const playersText = document.getElementById("players-text");
  const mapText = document.getElementById("map-text");
  const startServerBtn = document.getElementById("start-server");
  const stopServerBtn = document.getElementById("stop-server");
  const refreshStatusBtn = document.getElementById("refresh-status");
  const commandInput = document.getElementById("command-input");
  const sendCommandBtn = document.getElementById("send-command");
  const commandResponse = document.getElementById("command-response");
  const getInfoBtn = document.getElementById("get-info");
  const serverDetailedInfo = document.getElementById("server-detailed-info");

  // Check server status on page load
  setTimeout(checkServerStatus, 500); // Add a small delay to ensure API is ready

  // Event listeners
  startServerBtn.addEventListener("click", startServer);
  stopServerBtn.addEventListener("click", stopServer);
  refreshStatusBtn.addEventListener("click", checkServerStatus);
  sendCommandBtn.addEventListener("click", sendCommand);
  getInfoBtn.addEventListener("click", getServerInfo);
  commandInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      sendCommand();
    }
  });

  // Functions
  async function checkServerStatus() {
    try {
      statusText.textContent = "Checking...";
      const response = await fetch("/api/status");
      const data = await response.json();

      if (data.isRunning) {
        statusText.textContent = "Online";
        statusText.className = "online";
        startServerBtn.disabled = true;
        stopServerBtn.disabled = false;
        sendCommandBtn.disabled = false;
        getInfoBtn.disabled = false;

        // Display server info if available
        if (data.serverInfo) {
          serverInfo.classList.remove("hidden");
          motdText.textContent = data.serverInfo.motd;
          playersText.textContent = `${data.serverInfo.numPlayers}/${data.serverInfo.maxPlayers}`;
          mapText.textContent = data.serverInfo.map;
        }
      } else {
        statusText.textContent = "Offline";
        statusText.className = "offline";
        startServerBtn.disabled = false;
        stopServerBtn.disabled = true;
        sendCommandBtn.disabled = true;
        getInfoBtn.disabled = true;
        serverInfo.classList.add("hidden");
      }
    } catch (error) {
      statusText.textContent = "Error checking status";
      console.error("Error checking server status:", error);
    }
  }

  async function startServer() {
    try {
      startServerBtn.disabled = true;
      startServerBtn.textContent = "Starting...";

      const response = await fetch("/api/start", {
        method: "POST",
      });

      const data = await response.json();

      if (data.success) {
        alert("Server starting. This may take a moment...");
        setTimeout(checkServerStatus, 5000); // Check status after 5 seconds
      } else {
        alert(`Failed to start server: ${data.message}`);
        startServerBtn.disabled = false;
      }
    } catch (error) {
      alert("Error starting server");
      console.error("Error starting server:", error);
      startServerBtn.disabled = false;
    } finally {
      startServerBtn.textContent = "Start Server";
    }
  }

  async function stopServer() {
    if (!confirm("Are you sure you want to stop the server?")) {
      return;
    }

    try {
      stopServerBtn.disabled = true;
      stopServerBtn.textContent = "Stopping...";

      const response = await fetch("/api/stop", {
        method: "POST",
      });

      const data = await response.json();

      if (data.success) {
        alert("Server stopping. This may take a moment...");
        setTimeout(checkServerStatus, 5000); // Check status after 5 seconds
      } else {
        alert(`Failed to stop server: ${data.message}`);
        stopServerBtn.disabled = false;
      }
    } catch (error) {
      alert("Error stopping server");
      console.error("Error stopping server:", error);
      stopServerBtn.disabled = false;
    } finally {
      stopServerBtn.textContent = "Stop Server";
    }
  }

  async function sendCommand() {
    const command = commandInput.value.trim();

    if (!command) {
      alert("Please enter a command");
      return;
    }

    try {
      sendCommandBtn.disabled = true;
      commandResponse.innerHTML = "<p>Sending command...</p>";

      const response = await fetch("/api/command", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ command }),
      });

      const data = await response.json();

      if (data.success) {
        commandResponse.innerHTML = `<pre>${
          data.response || "Command executed successfully"
        }</pre>`;
        commandInput.value = ""; // Clear input on success
      } else {
        commandResponse.innerHTML = `<p>Error: ${data.message}</p>`;
      }
    } catch (error) {
      commandResponse.innerHTML = "<p>Error sending command</p>";
      console.error("Error sending command:", error);
    } finally {
      sendCommandBtn.disabled = false;
    }
  }

  async function getServerInfo() {
    try {
      getInfoBtn.disabled = true;
      serverDetailedInfo.innerHTML = "<p>Loading server information...</p>";

      const response = await fetch("/api/info");
      const data = await response.json();

      if (data.success) {
        // Format the info as a nice HTML table
        let html = "<table><tbody>";

        for (const [key, value] of Object.entries(data.info)) {
          if (key === "players") {
            html += `<tr><td>Players:</td><td>${
              data.info.players.join(", ") || "None"
            }</td></tr>`;
          } else {
            html += `<tr><td>${key}:</td><td>${value}</td></tr>`;
          }
        }

        html += "</tbody></table>";
        serverDetailedInfo.innerHTML = html;
      } else {
        serverDetailedInfo.innerHTML = `<p>Error: ${data.message}</p>`;
      }
    } catch (error) {
      serverDetailedInfo.innerHTML = "<p>Error getting server information</p>";
      console.error("Error getting server info:", error);
    } finally {
      getInfoBtn.disabled = false;
    }
  }
});
