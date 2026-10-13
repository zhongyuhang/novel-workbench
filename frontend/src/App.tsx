import { useEffect, useState } from "react";
import { SessionGate } from "./components/SessionGate.tsx";
import { NovelLibraryPage } from "./pages/NovelLibraryPage.tsx";
import { WorkspacePage } from "./pages/WorkspacePage.tsx";

type Route =
  | { kind: "library" }
  | { kind: "workspace"; novelId: string; chapterId: string | null };

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

function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  const chapter = /^\/novels\/([^/]+)\/chapters\/([^/]+)$/.exec(path);
  if (chapter?.[1] && chapter[2]) {
    return { kind: "workspace", novelId: decodeURIComponent(chapter[1]), chapterId: decodeURIComponent(chapter[2]) };
  }
  const novel = /^\/novels\/([^/]+)$/.exec(path);
  if (novel?.[1]) {
    return { kind: "workspace", novelId: decodeURIComponent(novel[1]), chapterId: null };
  }
  return { kind: "library" };
}
