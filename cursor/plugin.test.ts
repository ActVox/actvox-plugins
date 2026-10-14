import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = import.meta.dir;

function read(path: string): string {
  return readFileSync(join(root, path), "utf8");
}

function json(path: string): Record<string, unknown> {
  return JSON.parse(read(path)) as Record<string, unknown>;
}

describe("ActVox Cursor plugin", () => {
  test("manifest names the plugin and declares the API key variable", () => {
    const manifest = json(".cursor-plugin/plugin.json");
    expect(manifest.name).toBe("actvox");
    expect(manifest.logo).toBe("assets/logo.png");
    const variables = manifest.variables as {
      type: string;
      required: string[];
      properties: Record<string, { type: string }>;
    };
    expect(variables.type).toBe("object");
    expect(variables.required).toContain("ACTVOX_API_KEY");
    expect(variables.properties.ACTVOX_API_KEY?.type).toBe("string");
  });

  test("mcp.json points at the hosted server and only the declared placeholder", () => {
    const mcp = json("mcp.json") as {
      mcpServers: Record<string, { url: string; headers: Record<string, string> }>;
    };
    const server = mcp.mcpServers.actvox;
    expect(server?.url).toBe("https://api.actvox.com/mcp");
    expect(server?.headers.Authorization).toBe("Bearer ${ACTVOX_API_KEY}");
    const placeholders = JSON.stringify(mcp).match(/\$\{[A-Z0-9_]+\}/g) ?? [];
    const manifest = json(".cursor-plugin/plugin.json") as {
      variables: { properties: Record<string, unknown> };
    };
    for (const placeholder of placeholders) {
      const name = placeholder.slice(2, -1);
      expect(manifest.variables.properties).toHaveProperty(name);
    }
  });

  test("the package contains no API key", () => {
    for (const path of [".cursor-plugin/plugin.json", "mcp.json", "README.md", "skills/actvox/SKILL.md", "commands/actvox.md"]) {
      expect(read(path)).not.toMatch(/ratx_v1_/);
    }
  });

  test("logo is a square PNG with a background", () => {
    const png = readFileSync(join(root, "assets/logo.png"));
    expect(png.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
    expect(png.readUInt32BE(16)).toBe(512);
    expect(png.readUInt32BE(20)).toBe(512);
    expect(png[25]).toBe(2);
  });

  test("skill and command name themselves for discovery", () => {
    expect(read("skills/actvox/SKILL.md")).toMatch(/^---\nname: actvox\n/);
    expect(read("commands/actvox.md")).toMatch(/^---\nname: actvox\n/);
  });
});
