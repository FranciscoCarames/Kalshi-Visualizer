import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "@bakeoff/shared/tokens.css";
import { mount } from "svelte";
import App from "./App.svelte";

mount(App, { target: document.getElementById("root")! });
