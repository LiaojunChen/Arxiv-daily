import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const repositoryName = process.env.GITHUB_REPOSITORY?.split("/").at(-1);
const base =
  process.env.VITE_BASE_PATH || (repositoryName ? `/${repositoryName}/` : "/");

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base,
});
