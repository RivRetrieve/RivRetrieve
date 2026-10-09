import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    actionTimeout: 10000,
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
