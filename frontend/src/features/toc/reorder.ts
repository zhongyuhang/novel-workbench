export type DropPlace = "before" | "after";

/** Index in the destination list after the dragged id has been removed. Matches chapter move. */
export function insertionIndex(
  ids: string[],
  draggedId: string,
  targetId: string,
  place: DropPlace,
): number {
  const without = ids.filter((id) => id !== draggedId);
  const at = without.indexOf(targetId);
  if (at < 0) {
    return without.length;
  }
  return place === "after" ? at + 1 : at;
}

export function orderAfterInsert(ids: string[], draggedId: string, index: number): string[] {
  const without = ids.filter((id) => id !== draggedId);
  const next = [...without];
  next.splice(Math.max(0, Math.min(index, next.length)), 0, draggedId);
  return next;
}

export function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index]);
}

/**
 * Sort index to send to the chapter move API, or null when the drop would not change order.
 * `sourceIds` and `targetIds` are the current order in each volume (the dragged chapter is in source).
 */
export function planChapterMove(
  sourceIds: string[],
  draggedId: string,
  targetIds: string[],
  targetId: string | null,
  place: DropPlace | "end",
): number | null {
  if (targetId !== null && targetId === draggedId) {
    return null;
  }
  const index =
    place === "end" || targetId === null
      ? targetIds.filter((id) => id !== draggedId).length
      : insertionIndex(targetIds, draggedId, targetId, place);
  const next = orderAfterInsert(targetIds, draggedId, index);
  if (sameIds(sourceIds, targetIds) && sameIds(sourceIds, next)) {
    return null;
  }
  return index;
}

export function planVolumeMove(
  ids: string[],
  draggedId: string,
  targetId: string,
  place: DropPlace,
): string[] | null {
  if (draggedId === targetId || !ids.includes(draggedId) || !ids.includes(targetId)) {
    return null;
  }
  const index = insertionIndex(ids, draggedId, targetId, place);
  const next = orderAfterInsert(ids, draggedId, index);
  return sameIds(ids, next) ? null : next;
}

export function moveVolumeToStart(ids: string[], draggedId: string): string[] | null {
  if (!ids.includes(draggedId) || ids[0] === draggedId) {
    return null;
  }
  return [draggedId, ...ids.filter((id) => id !== draggedId)];
}
