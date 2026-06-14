import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "./tokens.css";
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import { createRoot } from "react-dom/client";
import App from "./App";

ModuleRegistry.registerModules([AllCommunityModule]);   // once, before any grid mounts

createRoot(document.getElementById("root")!).render(<App />);
