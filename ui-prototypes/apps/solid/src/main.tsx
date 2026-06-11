import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "@bakeoff/shared/tokens.css";
import { render } from "solid-js/web";
import App from "./App";

const MINIMAL = false;
if (MINIMAL) {
  render(() => <div style="color:gold;padding:20px;font-family:monospace">SOLID OK — setup works</div>, document.getElementById("root")!);
} else {
  render(() => <App />, document.getElementById("root")!);
}
