/**
 * CodeMirror 6 theme + highlight style matching the MC pixel theme.
 * Uses CSS custom properties from variables.css.
 */
import { EditorView } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

/** Base editor theme — dark MC pixel style */
export const mcEditorTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: 'var(--mc-bg-deep)',
      color: 'var(--mc-text-primary)',
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '14px',
      lineHeight: '1.6',
    },
    '.cm-content': {
      caretColor: 'var(--mc-gold)',
      padding: '8px 0',
    },
    '.cm-cursor, .cm-dropCursor': {
      borderLeftColor: 'var(--mc-gold)',
      borderLeftWidth: '2px',
    },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
      backgroundColor: 'rgba(221, 165, 32, 0.25)',
    },
    '.cm-activeLine': {
      backgroundColor: 'rgba(255, 255, 255, 0.04)',
    },
    '.cm-gutters': {
      backgroundColor: 'var(--mc-bg-main)',
      color: 'var(--mc-text-dim)',
      border: 'none',
      borderRight: '2px solid var(--mc-border)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'rgba(255, 255, 255, 0.06)',
      color: 'var(--mc-text-secondary)',
    },
    '.cm-lineNumbers .cm-gutterElement': {
      padding: '0 8px 0 4px',
      minWidth: '32px',
    },
    // Autocomplete dropdown
    '.cm-tooltip': {
      backgroundColor: 'var(--mc-bg-card)',
      border: '2px solid var(--mc-border)',
      boxShadow: '4px 4px 0 rgba(0,0,0,0.5)',
      color: 'var(--mc-text-primary)',
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '13px',
    },
    '.cm-tooltip-autocomplete': {
      '& > ul': {
        fontFamily: "'GNU Unifont', var(--mc-font-mono)",
        maxHeight: '200px',
      },
      '& > ul > li': {
        padding: '4px 8px',
        lineHeight: '1.4',
      },
      '& > ul > li[aria-selected]': {
        backgroundColor: 'var(--mc-bg-hover)',
        color: 'var(--mc-gold)',
      },
    },
    // Lint diagnostics
    '.cm-diagnostic-error': {
      borderLeft: '3px solid var(--mc-red)',
      backgroundColor: 'rgba(176, 46, 38, 0.15)',
      color: 'var(--mc-text-primary)',
      padding: '4px 8px',
    },
    '.cm-diagnostic-warning': {
      borderLeft: '3px solid var(--mc-gold)',
      backgroundColor: 'rgba(221, 165, 32, 0.1)',
      color: 'var(--mc-text-primary)',
      padding: '4px 8px',
    },
    '.cm-lintRange-error': {
      backgroundImage: 'none',
      textDecoration: 'wavy underline var(--mc-red)',
      textUnderlineOffset: '3px',
    },
    '.cm-lintRange-warning': {
      backgroundImage: 'none',
      textDecoration: 'wavy underline var(--mc-gold)',
      textUnderlineOffset: '3px',
    },
    // Scrollbar
    '.cm-scroller': {
      overflow: 'auto',
      scrollbarWidth: 'thin',
      scrollbarColor: 'var(--mc-border) transparent',
    },
  },
  { dark: true }
)

/** Syntax highlight style mapping StreamLanguage tokens to MC colors */
const mcHighlight = HighlightStyle.define([
  // /command and command name → green
  { tag: t.keyword, color: 'var(--mc-syn-command)', fontWeight: 'bold' },
  // @selector → magenta
  { tag: t.className, color: 'var(--mc-syn-selector)' },
  // "string" → orange
  { tag: t.string, color: 'var(--mc-syn-string)' },
  // 123 → red
  { tag: t.number, color: 'var(--mc-syn-number)' },
  // ~5 ^-3 relative coords → cyan
  { tag: t.atom, color: 'var(--mc-syn-optional)' },
  // as, at, if, run, true, false → yellow
  { tag: t.operator, color: 'var(--mc-syn-required)' },
  // Generic identifiers (param values) → light text
  { tag: t.variableName, color: 'var(--mc-text-primary)' },
  // # comments → dim
  { tag: t.lineComment, color: 'var(--mc-text-dim)', fontStyle: 'italic' },
  // JSON braces
  { tag: t.brace, color: 'var(--mc-text-secondary)' },
  // Punctuation
  { tag: t.punctuation, color: 'var(--mc-text-dim)' },
])

/** Combined theme + highlighting extension */
export const mcTheme = [mcEditorTheme, syntaxHighlighting(mcHighlight)]
