// Links into the public repository. Paths are repo-relative; the repository goes public after submission.

export const REPO_URL = 'https://github.com/ethanrom/Exemplar'

/** `https://github.com/ethanrom/Exemplar/blob/main/<path>` with an optional line anchor or heading anchor. */
export function blob(path: string, anchor?: string | number): string {
  const base = `${REPO_URL}/blob/main/${path}`
  if (anchor === undefined) return base
  return typeof anchor === 'number' ? `${base}#L${anchor}` : `${base}#${anchor}`
}

/** A folder in the repository. */
export function tree(path: string): string {
  return `${REPO_URL}/tree/main/${path}`
}
