// Minimal path-based routing. The studio is a second route in the same app (PRD §8.2);
// a full router library is unwarranted for two routes, so we switch on pathname. Deep
// links to /studio resolve because Vite's dev server serves index.html for all paths and
// FastAPI has an explicit /studio SPA fallback (see app/main.py).

import ChatPage from "./ChatPage";
import StudioPage from "./studio/StudioPage";

export default function App() {
  if (window.location.pathname.startsWith("/studio")) {
    return <StudioPage />;
  }
  return <ChatPage />;
}
