// Client-side mirror of the backend CODE_LIKE_PATTERN (backend/schemas.py).
// Rejecting code-like input here gives instant feedback and spares a round
// trip the server would only answer with a 422.

// Matches script/markup tags, template and shell interpolation, SQL fragments,
// javascript: URIs, and inline event handlers.
const CODE_LIKE_PATTERN =
  /(<\s*script)|(<\s*\/?\s*[a-z]+\s*>)|(\{\{)|(\$\{)|(;\s*(drop|select|insert)\s)|(--\s)|(\bunion\s+select\b)|(javascript:)|(\bon\w+\s*=)/i;

// Returns true when the value looks like code and should be rejected.
export function isCodeLike(value: string): boolean {
  return CODE_LIKE_PATTERN.test(value);
}
