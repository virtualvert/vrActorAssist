// Character routing for Send files (spec §8.4): " - Character" at the end of a file name says who
// the line belongs to. Same rule as the v0.3 director (director_client_ws.py parse_character_name)
// and agent/files.py.

/** `Scene 4 - Diego.mp3` → `Diego`. The last " - " wins; null without the pattern. */
export function parseCharacterName(filename: string): string | null {
  const at = filename.lastIndexOf(" - ");
  if (at < 0) return null;
  const rest = filename.slice(at + 3);
  const dot = rest.lastIndexOf(".");
  const character = (dot < 0 ? rest : rest.slice(0, dot)).trim();
  return character || null;
}

/** The file name of a path inside the folder (forward slashes). */
export function baseName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

export interface FileGroups {
  /** Character → paths, characters in the order they first appear. */
  characters: Map<string, string[]>;
  /** Paths without a character. */
  loose: string[];
}

export function groupFiles(paths: string[]): FileGroups {
  const characters = new Map<string, string[]>();
  const loose: string[] = [];
  for (const path of paths) {
    const character = parseCharacterName(baseName(path));
    if (character === null) loose.push(path);
    else characters.set(character, [...(characters.get(character) ?? []), path]);
  }
  return { characters, loose };
}

/**
 * Who gets what. `byCharacter` maps a character to an actor id; `byFile` overrides it for one
 * path. Paths without an actor are left out. Returns the items for the sendFiles call and the
 * problems that stop sending (two files with the same name for one actor).
 */
export function assignments(
  paths: string[],
  byCharacter: Record<string, string>,
  byFile: Record<string, string>,
): { items: { path: string; actorId: string }[]; clashes: string[] } {
  const items: { path: string; actorId: string }[] = [];
  const seen = new Map<string, string>();
  const clashes: string[] = [];
  for (const path of paths) {
    const character = parseCharacterName(baseName(path));
    const actorId = byFile[path] || (character !== null ? byCharacter[character] : "") || "";
    if (!actorId) continue;
    const key = `${actorId}\u0000${baseName(path)}`;
    if (seen.has(key)) clashes.push(baseName(path));
    seen.set(key, path);
    items.push({ path, actorId });
  }
  return { items, clashes: [...new Set(clashes)] };
}
