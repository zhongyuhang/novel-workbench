export type Route =
  | { kind: "library" }
  | { kind: "settings" }
  | { kind: "workspace"; novelId: string; chapterId: string | null };

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  if (path === "/settings") {
    return { kind: "settings" };
  }
  const chapter = /^\/novels\/([^/]+)\/chapters\/([^/]+)$/.exec(path);
  if (chapter?.[1] && chapter[2]) {
    return {
      kind: "workspace",
      novelId: decodeURIComponent(chapter[1]),
      chapterId: decodeURIComponent(chapter[2]),
    };
  }
  const novel = /^\/novels\/([^/]+)$/.exec(path);
  if (novel?.[1]) {
    return { kind: "workspace", novelId: decodeURIComponent(novel[1]), chapterId: null };
  }
  return { kind: "library" };
}

export function workspaceHash(novelId: string, chapterId: string | null): string {
  if (chapterId) {
    return `#/novels/${novelId}/chapters/${chapterId}`;
  }
  return `#/novels/${novelId}`;
}
