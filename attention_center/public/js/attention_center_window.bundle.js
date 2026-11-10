// The window bundle, loaded by the launcher bundle when the window first opens (§7.1, NFR-PERF-02). The two
// bundles share no module instances: the launcher hands the window its store, api and guard through this global.
import { createWindow } from "./attention_center/ui/window.js";

window.attention_center_window = { createWindow };
