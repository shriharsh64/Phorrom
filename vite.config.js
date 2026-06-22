import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Port 1420 matches the sidecar CORS allowlist (and Tauri's default dev port).
export default defineConfig({
    plugins: [react()],
    server: { port: 1420, strictPort: true },
});
