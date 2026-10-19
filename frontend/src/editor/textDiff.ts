export type DiffOp = "equal" | "insert" | "delete";

export type DiffHunk = {
  op: DiffOp;
  text: string;
};

const MAX_CELLS = 160_000;

export function diffLines(left: string, right: string): DiffHunk[] {
  if (left === right) {
    return left === "" ? [] : [{ op: "equal", text: left }];
  }
  const older = left.split("\n");
  const newer = right.split("\n");
  if (older.length * newer.length > MAX_CELLS) {
    const hunks: DiffHunk[] = [];
    if (left !== "") {
      hunks.push({ op: "delete", text: left });
    }
    if (right !== "") {
      hunks.push({ op: "insert", text: right });
    }
    return hunks;
  }
  const scores = buildScores(older, newer);
  return walk(older, newer, scores);
}

function buildScores(older: string[], newer: string[]): number[][] {
  const rows = older.length;
  const columns = newer.length;
  const scores = Array.from({ length: rows + 1 }, () => Array<number>(columns + 1).fill(0));
  for (let row = rows - 1; row >= 0; row -= 1) {
    for (let column = columns - 1; column >= 0; column -= 1) {
      const matched = older[row] === newer[column];
      const next = scores[row + 1]?.[column + 1] ?? 0;
      const down = scores[row + 1]?.[column] ?? 0;
      const across = scores[row]?.[column + 1] ?? 0;
      const cell = scores[row];
      if (cell) {
        cell[column] = matched ? next + 1 : Math.max(down, across);
      }
    }
  }
  return scores;
}

function walk(older: string[], newer: string[], scores: number[][]): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  let row = 0;
  let column = 0;
  while (row < older.length && column < newer.length) {
    if (older[row] === newer[column]) {
      push(hunks, "equal", older[row] ?? "");
      row += 1;
      column += 1;
      continue;
    }
    const down = scores[row + 1]?.[column] ?? 0;
    const across = scores[row]?.[column + 1] ?? 0;
    if (down >= across) {
      push(hunks, "delete", older[row] ?? "");
      row += 1;
    } else {
      push(hunks, "insert", newer[column] ?? "");
      column += 1;
    }
  }
  while (row < older.length) {
    push(hunks, "delete", older[row] ?? "");
    row += 1;
  }
  while (column < newer.length) {
    push(hunks, "insert", newer[column] ?? "");
    column += 1;
  }
  return hunks;
}

function push(hunks: DiffHunk[], op: DiffOp, line: string): void {
  const last = hunks.at(-1);
  if (last && last.op === op) {
    last.text = `${last.text}\n${line}`;
    return;
  }
  hunks.push({ op, text: line });
}
