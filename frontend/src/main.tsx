import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "ol/ol.css";
import "./styles.css";
import RootApp from "@mapper-app";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
);
