import { useEffect, useState } from "react";
import { SessionGate } from "./components/SessionGate.tsx";
import { NovelLibraryPage } from "./pages/NovelLibraryPage.tsx";
import { WorkspacePage } from "./pages/WorkspacePage.tsx";
import { parseHash, type Route } from "./routes.ts";

export function App() {
  const route = useHashRoute();
  return (
    <SessionGate>
      {route.kind === "library" ? (
        <NovelLibraryPage />
      ) : (
        <WorkspacePage novelId={route.novelId} chapterId={route.chapterId} />
      )}
    </SessionGate>
  );
}

function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
    };
    window.addEventListener("hashchange", onChange);
    return () => {
      window.removeEventListener("hashchange", onChange);
    };
  }, []);

  return route;
}
