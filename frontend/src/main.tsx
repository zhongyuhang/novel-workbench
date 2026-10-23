import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { installTheme } from "./theme.ts";
import "./index.css";

installTheme();

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root is missing.");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
