/**
 * A small Python tokeniser for the code panel.
 *
 * WHY hand-written rather than pulling in Prism or highlight.js: those ship a
 * grammar for a hundred languages and a stylesheet with opinions, and this app
 * highlights exactly one language whose snippets it generates itself. The whole
 * tokeniser is sixty lines, adds nothing to the bundle, and -- more usefully --
 * means the token categories are chosen for what the reader of THESE snippets
 * needs to see: the comment lines that explain a decision are given as much
 * visual weight as the code, because in a glass box the comments are the
 * argument.
 *
 * It returns tokens rather than HTML on purpose. The caller renders them as
 * React elements, so there is no innerHTML anywhere and a column name
 * containing `<script>` is text, not markup.
 */

const KEYWORDS = new Set([
  'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def',
  'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if',
  'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise',
  'return', 'try', 'while', 'with', 'yield',
])

const CONSTANTS = new Set(['True', 'False', 'None'])

const BUILTINS = new Set([
  'abs', 'bool', 'dict', 'enumerate', 'float', 'int', 'len', 'list', 'max',
  'min', 'print', 'range', 'round', 'set', 'sorted', 'str', 'sum', 'tuple',
  'zip',
])

/**
 * One pass, one regex. The alternation order IS the precedence order: a `#`
 * inside a string must be part of the string, so strings are matched before
 * comments; a keyword inside an identifier must not match, so identifiers are
 * matched whole and classified afterwards.
 */
const TOKEN_RE = new RegExp(
  [
    '(?<string>(?:[rbfu]{0,2})(?:"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'))',
    '(?<comment>#[^\\n]*)',
    '(?<number>\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)',
    '(?<name>[A-Za-z_][A-Za-z0-9_]*)',
    '(?<op>[+\\-*/%=<>!&|^~@]+)',
    '(?<punct>[()\\[\\]{},.:;])',
  ].join('|'),
  'g',
)

/**
 * Split Python source into `{ type, text }` tokens.
 *
 * Anything the regex does not match (whitespace, stray characters) is emitted
 * as a `plain` token rather than dropped, so joining every token's text back
 * together reproduces the input exactly. That property is what makes it safe to
 * render the tokens instead of the source: nothing can be silently lost.
 *
 * @param {string} source
 * @returns {{type: string, text: string}[]}
 */
export function tokenisePython(source) {
  const tokens = []
  let cursor = 0

  for (const match of source.matchAll(TOKEN_RE)) {
    if (match.index > cursor) {
      tokens.push({ type: 'plain', text: source.slice(cursor, match.index) })
    }

    const groups = match.groups ?? {}
    const text = match[0]
    let type = 'plain'

    if (groups.string != null) type = 'string'
    else if (groups.comment != null) type = 'comment'
    else if (groups.number != null) type = 'number'
    else if (groups.op != null) type = 'operator'
    else if (groups.punct != null) type = 'punct'
    else if (groups.name != null) {
      if (KEYWORDS.has(text)) type = 'keyword'
      else if (CONSTANTS.has(text)) type = 'constant'
      else if (BUILTINS.has(text)) type = 'builtin'
      else {
        // A name followed by "(" is being called. Looking ahead in the source
        // rather than tracking parser state keeps this a tokeniser instead of
        // half a parser, and it is right often enough to be worth the colour.
        const after = source.slice(match.index + text.length)
        type = /^\s*\(/.test(after) ? 'call' : 'name'
      }
    }

    tokens.push({ type, text })
    cursor = match.index + text.length
  }

  if (cursor < source.length) {
    tokens.push({ type: 'plain', text: source.slice(cursor) })
  }
  return tokens
}

/**
 * Tokenise, then split into lines so the panel can render a numbered gutter.
 *
 * Splitting after tokenising rather than before matters for triple-quoted
 * strings, which legitimately span lines: tokenising line by line would restart
 * the string state on every line and mis-colour the rest of the file.
 *
 * @param {string} source
 * @returns {{type: string, text: string}[][]} one token array per line
 */
export function tokeniseLines(source) {
  const lines = [[]]

  for (const token of tokenisePython(source)) {
    const parts = token.text.split('\n')
    parts.forEach((part, index) => {
      if (index > 0) lines.push([])
      if (part) lines[lines.length - 1].push({ type: token.type, text: part })
    })
  }
  return lines
}
