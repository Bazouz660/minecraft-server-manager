// src/start-bat-helper.ts
import fs from "fs";
import { join } from "path";

export async function examineStartBat(
  serverPath: string,
  startScriptName: string
): Promise<string> {
  try {
    const scriptPath = join(serverPath, startScriptName);

    if (!fs.existsSync(scriptPath)) {
      return `Start script not found: ${scriptPath}`;
    }

    const content = fs.readFileSync(scriptPath, "utf8");
    return content;
  } catch (error) {
    return `Error reading start script: ${error}`;
  }
}

export function fixStartBat(
  serverPath: string,
  startScriptName: string
): boolean {
  try {
    const scriptPath = join(serverPath, startScriptName);

    if (!fs.existsSync(scriptPath)) {
      return false;
    }

    // Read the original content
    const originalContent = fs.readFileSync(scriptPath, "utf8");

    // Create a backup
    fs.writeFileSync(`${scriptPath}.backup`, originalContent, "utf8");

    // Fix common issues in batch files
    let fixedContent = originalContent;

    // Fix paths without quotes
    fixedContent = fixedContent.replace(
      /(\w:[\\/](?:[^\s"]+[\\/])*[^\s"]+\s)/g,
      '"$1"'
    );

    // Save the fixed batch file
    fs.writeFileSync(scriptPath, fixedContent, "utf8");

    return true;
  } catch (error) {
    console.error("Error fixing start.bat:", error);
    return false;
  }
}
