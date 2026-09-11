import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { registerServiceWorker } from "./registerServiceWorker";

// Isolated prototype, reachable at /tier1-test without touching the main
// app flow. See src/prototypes/Tier1Test.tsx.
const isTier1Test = window.location.pathname === "/tier1-test";
const RootComponent = isTier1Test
  ? React.lazy(() => import("./prototypes/Tier1Test"))
  : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <React.Suspense fallback={null}>
      <RootComponent />
    </React.Suspense>
  </React.StrictMode>
);

registerServiceWorker();
