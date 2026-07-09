import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import CoachView from "./components/CoachView.jsx";
import "./styles.css";

// Minimal manual "routing": this app has no router dependency, and a single
// public, unauthenticated route (/coach/:token - see backend/coaching.py's
// module docstring) doesn't justify adding one. A path starting with
// /coach/ renders the standalone public CoachView instead of the whole
// signed-in <App/> shell - no account/session logic runs at all on this
// path, since a coach viewing a shared link has no account requirement.
const coachViewMatch = window.location.pathname.match(/\/coach\/([^/?#]+)/);

createRoot(document.getElementById("root")).render(
  <StrictMode>
    {coachViewMatch ? <CoachView token={coachViewMatch[1]} /> : <App />}
  </StrictMode>
);
