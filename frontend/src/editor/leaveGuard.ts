export const UNSAVED_LEAVE_MESSAGE =
  "当前章节还有未保存的修改。离开或切换章节会丢掉这些修改。确定离开？";

export function allowChapterLeave(
  unsaved: boolean,
  confirmLeave: (message: string) => boolean,
): boolean {
  if (!unsaved) {
    return true;
  }
  return confirmLeave(UNSAVED_LEAVE_MESSAGE);
}
